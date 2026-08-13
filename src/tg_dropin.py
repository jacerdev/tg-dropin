import os
import time
import json
import queue
import logging
import threading
import mimetypes
import uuid
import urllib.request
import urllib.parse
import urllib.error
import contextlib
import traceback

logger = logging.getLogger("tg_dropin")


class TelegramSidecar:
    def __init__(self, bot_token, chat_id):
        """
        Initializes the Telegram Sidecar.
        :param bot_token: The Telegram bot token.
        :param chat_id: A single chat ID (string/int) or a list of authorized chat IDs.
        """
        if not bot_token or not chat_id:
            raise ValueError("bot_token and chat_id are required.")
            
        self.bot_token = str(bot_token)
        
        if not isinstance(chat_id, list):
            chat_id = [chat_id]
        self.chat_ids = [str(c) for c in chat_id]
        
        self.commands = {}
        self.default_handler = None
        self._stop_event = threading.Event()
        self._thread = None
        self._worker_thread = None
        self._handler_queue = queue.Queue()
        self.offset = None
        
        # Register the built-in help command
        self.command("help", description="Show this help message")(self._builtin_help)

    def __enter__(self):
        self.start()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        
    @contextlib.contextmanager
    def notify_exceptions(self):
        """Context manager that sends any uncaught exceptions to Telegram as plain text."""
        try:
            yield
        except Exception as e:
            tb = traceback.format_exc()
            error_msg = f"Exception Occurred\n\n{type(e).__name__}: {e}\n\n{tb}"
            if len(error_msg) > 4000:
                error_msg = error_msg[:4000] + "\n...[truncated]"
            self.send_message(error_msg)
            raise

    def command(self, name, description=""):
        """Decorator to register a command handler.
        Usage:
            @bot.command("set", description="Update a configuration parameter")
            def handle_set(arg):
                args = arg.split()
                if len(args) < 2:
                    return "⚠️ Usage: /set <param> <value>"
                param, val = args[0], args[1]
                if param not in config:
                    return f"⚠️ Unknown parameter: {param}"
                config[param] = val
                return f"Updated {param} to {val}"
        """
        def decorator(func):
            self.commands[name.lower()] = {"func": func, "description": description}
            return func
        return decorator

    def _builtin_help(self, arg=""):
        lines = ["Available commands:\n"]
        for cmd, info in self.commands.items():
            desc = info["description"]
            lines.append(f"/{cmd} — {desc}" if desc else f"/{cmd}")
        return "\n".join(lines)

    def set_default_handler(self, func):
        """Sets a fallback handler for any message that doesn't match a registered command."""
        self.default_handler = func
        return func

    def start(self, poll_interval=1.0):
        """Starts the background polling thread and command worker thread.

        Calling start() while already running is a no-op (logs a warning).
        """
        if self._thread and self._thread.is_alive():
            logger.warning("start() called while already running; ignoring.")
            return

        self._stop_event.clear()

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="TelegramBotWorker",
        )
        self._worker_thread.start()

        self._thread = threading.Thread(
            target=self._poll_loop,
            args=(poll_interval,),
            daemon=True,
            name="TelegramBotPoller",
        )
        self._thread.start()
        logger.info("Telegram bot polling started in background.")

    def stop(self):
        """Signals the polling thread to stop, drains the worker queue, and waits for both to finish."""
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=5)

        # Send a sentinel to unblock the worker and let it exit cleanly.
        self._handler_queue.put(None)
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)

        logger.info("Telegram bot polling stopped.")


    def _poll_loop(self, poll_interval):
        # Discard any backlog that accumulated before this run.
        self._get_updates(timeout=1)

        while not self._stop_event.is_set():
            try:
                updates = self._get_updates(timeout=5)
                for update in updates:
                    message = update.get("message", {})
                    text = message.get("text", "").strip()
                    sender_id = str(message.get("chat", {}).get("id", ""))

                    if text and sender_id in self.chat_ids:  # security whitelist
                        self._handler_queue.put((text, sender_id))
            except Exception:
                logger.warning("Unexpected error in poll loop.", exc_info=True)

            if not self._stop_event.is_set():
                time.sleep(poll_interval)

    def _get_updates(self, timeout):
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?timeout={timeout}"
        if self.offset:
            url += f"&offset={self.offset}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout + 5) as response:
                data = json.loads(response.read().decode())
                if data.get("ok"):
                    results = data.get("result", [])
                    if results:
                        self.offset = results[-1]["update_id"] + 1
                    return results
                else:
                    logger.warning(
                        "Telegram API returned ok=false: %s",
                        data.get("description", "unknown error"),
                    )
        except urllib.error.URLError as e:
            logger.warning("Network error fetching updates: %s", e)
        except json.JSONDecodeError as e:
            logger.warning("Failed to decode Telegram response: %s", e)
        except Exception as e:
            logger.warning("Unexpected error fetching updates: %s", e)
        return []


    def _worker_loop(self):
        """Drains the handler queue serially. Handlers never block the poller."""
        while True:
            item = self._handler_queue.get()
            if item is None:  # sentinel: stop requested
                self._handler_queue.task_done()
                break
            text, sender_id = item
            try:
                self._process_message(text, sender_id)
            except Exception:
                logger.error("Unexpected error in worker loop.", exc_info=True)
            finally:
                self._handler_queue.task_done()

    def _process_message(self, text, sender_id):
        """
        Process a single incoming message on the worker thread.
        If a handler returns a string, it will be sent as a reply to the sender.
        Send failures here are command-response failures and are logged at ERROR level.
        """
        parts = text.split(maxsplit=1)
        if not parts:
            return

        cmd = parts[0].lstrip("/").lower()
        arg = parts[1] if len(parts) > 1 else ""

        result = None
        if cmd in self.commands:
            try:
                result = self.commands[cmd]["func"](arg)
            except Exception as e:
                logger.error(
                    "Handler for command '%s' raised an exception: %s",
                    cmd, e, exc_info=True,
                )
                _send_telegram_text(
                    self.bot_token,
                    f"Error executing command '{cmd}': {e}",
                    targets=[sender_id],
                    failure_log_level=logging.ERROR,
                )
        elif self.default_handler:
            try:
                result = self.default_handler(text)
            except Exception as e:
                logger.error("Default handler raised an exception: %s", e, exc_info=True)
                _send_telegram_text(
                    self.bot_token,
                    f"Error in default handler: {e}",
                    targets=[sender_id],
                    failure_log_level=logging.ERROR,
                )
        else:
            _send_telegram_text(
                self.bot_token,
                f"Unknown command: {cmd}",
                targets=[sender_id],
                failure_log_level=logging.ERROR,
            )

        if isinstance(result, str):
            _send_telegram_text(self.bot_token, result, targets=[sender_id], failure_log_level=logging.ERROR)


    ############### Public API ###############

    def send_message(self, message, chat_id=None, parse_mode=None):
        """Send a text message. Broadcasts to all authorized chats if chat_id is omitted.

        :param parse_mode: Optional Telegram parse mode, e.g. "Markdown" or "HTML".
            Defaults to None (plain text).
        """
        if chat_id is None: targets = self.chat_ids
        elif isinstance(chat_id, (list, tuple)): targets = [str(c) for c in chat_id]
        else: targets = [str(chat_id)]

        return _send_telegram_text(
            self.bot_token,
            message,
            targets=targets,
            parse_mode=parse_mode,
            failure_log_level=logging.WARNING,
        )

    def send_file(self, file_path, caption="", chat_id=None):
        """Automatically determines whether to send as an image or document based on extension."""
        if chat_id is None: targets = self.chat_ids
        elif isinstance(chat_id, (list, tuple)): targets = [str(c) for c in chat_id]
        else: targets = [str(chat_id)]

        mime_type = mimetypes.guess_type(os.path.basename(file_path))[0] or "application/octet-stream"

        return _send_telegram_file(
            self.bot_token,
            targets,
            file_path,
            field_name="photo" if mime_type.startswith("image/") else "document",
            mime_type=mime_type,
            caption=caption,
        )


def _send_telegram_text(bot_token, message, targets, parse_mode=None, failure_log_level=logging.WARNING):
    """Send a text message to an explicit list of chat ID strings."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    all_success = True
    for target in targets:
        payload = {"chat_id": target, "text": message}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        data = urllib.parse.urlencode(payload).encode("utf-8")
        try:
            req = urllib.request.Request(url, data=data)
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            logger.log(failure_log_level, "Failed to send message to %s: %s", target, e)
            all_success = False
    return all_success

def _send_telegram_file(bot_token, targets, file_path, field_name, mime_type, caption=""):
    """Send a photo or document file to an explicit list of chat ID strings using multipart form-data."""
    if not os.path.exists(file_path):
        logger.error("File path does not exist: %s", file_path)
        return False

    with open(file_path, "rb") as f:
        file_data = f.read()

    filename = os.path.basename(file_path)
    url = f"https://api.telegram.org/bot{bot_token}/send{field_name.capitalize()}"

    all_success = True
    for target in targets:
        boundary = uuid.uuid4().hex
        body = bytearray()

        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
        body.extend(f"{target}\r\n".encode("utf-8"))

        if caption:
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
            body.extend(f"{caption}\r\n".encode("utf-8"))

        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8")
        )
        body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
        body.extend(file_data)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        }

        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            logger.error("Failed to send %s to %s: %s", field_name, target, e)
            all_success = False
    return all_success