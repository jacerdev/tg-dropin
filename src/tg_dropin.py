import os
import time
import json
import threading
import mimetypes
import uuid
import urllib.request
import urllib.parse
import urllib.error
import contextlib
import traceback

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
        """Context manager that sends any uncaught exceptions to Telegram."""
        try:
            yield
        except Exception as e:
            tb = traceback.format_exc()
            error_msg = f"🚨 **Exception Occurred**\n\n`{type(e).__name__}: {e}`\n\n```python\n{tb}\n```"
            if len(error_msg) > 4000:
                error_msg = error_msg[:4000] + "\n...[truncated]```"
            self.notify(error_msg)
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
        lines = ["**Available commands:**\n"]
        for cmd, info in self.commands.items():
            desc = info["description"]
            lines.append(f"/{cmd} — {desc}" if desc else f"/{cmd}")
        return "\n".join(lines)

    def set_default_handler(self, func):
        """Sets a fallback handler for any message that doesn't match a registered command."""
        self.default_handler = func
        return func

    def start(self, poll_interval=1.0):
        """Starts the background polling thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, 
            args=(poll_interval,), 
            daemon=True,
            name="TelegramBotPoller"
        )
        self._thread.start()
        print("Telegram bot polling started in background.")

    def stop(self):
        """Signals the polling thread to stop and waits for it to finish."""
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=5)
            print("Telegram bot polling stopped.")

    def _poll_loop(self, poll_interval):
        self._get_updates(timeout=1) # fetch once to clear old backlog on startup

        while not self._stop_event.is_set():
            try:
                updates = self._get_updates(timeout=5)
                for update in updates:
                    message = update.get("message", {})
                    text = message.get("text", "").strip()
                    sender_id = str(message.get("chat", {}).get("id", ""))
                    
                    if text and sender_id in self.chat_ids: # security whitelist
                        self._process_message(text, sender_id)
            except Exception:
                pass # silently catch so the daemon doesn't crash on network errors
            
            if not self._stop_event.is_set():
                time.sleep(poll_interval)

    def _get_updates(self, timeout):
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?timeout={timeout}"
        if self.offset:
            url += f"&offset={self.offset}"
            
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout+5) as response:
                data = json.loads(response.read().decode())
                if data.get("ok"):
                    results = data.get("result", [])
                    if results:
                        self.offset = results[-1]["update_id"] + 1
                    return results
        except (urllib.error.URLError, TimeoutError):
            pass
        except Exception:
            pass
        return []

    def _process_message(self, text, sender_id):
        """
        Process a single incoming message.
        If a handler returns a string, it will be sent as reply to the command.
        """
        parts = text.split(maxsplit=1)
        if not parts:
            return
            
        cmd = parts[0].lstrip('/').lower()
        arg = parts[1] if len(parts) > 1 else ""

        result = None
        if cmd in self.commands:
            try:
                result = self.commands[cmd]["func"](arg)
            except Exception as e:
                self.send_message(f"⚠️ Error executing command '{cmd}': {e}", chat_id=sender_id)
        elif self.default_handler:
            try:
                result = self.default_handler(text)
            except Exception as e:
                self.send_message(f"⚠️ Error in default handler: {e}", chat_id=sender_id)
        else:
            self.send_message(f"⚠️ Unknown command: {cmd}", chat_id=sender_id)
            
        if isinstance(result, str):
            self.send_message(result, chat_id=sender_id)

    def notify(self, message):
        """Alias for send_message, used to broadcast to all authorized chats."""
        return self.send_message(message)

    def send_message(self, message, chat_id=None):
        """Sends a text message. If chat_id is not provided, broadcasts to all authorized chats."""
        targets = [str(chat_id)] if chat_id else self.chat_ids
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        
        all_success = True
        for target in targets:
            data = urllib.parse.urlencode({'chat_id': target, 'text': message, 'parse_mode': 'Markdown'}).encode('utf-8')
            try:
                req = urllib.request.Request(url, data=data)
                urllib.request.urlopen(req, timeout=5)
            except Exception as e:
                print(f"Failed to send telegram message to {target}: {e}")
                all_success = False
        return all_success

    def send_file(self, file_path, caption="", chat_id=None):
        """Automatically determines whether to send as an image or document based on extension."""
        mime_type = mimetypes.guess_type(file_path)[0] or ''
        if mime_type.startswith('image/'):
            return self.send_image(file_path, caption, chat_id)
        return self.send_document(file_path, caption, chat_id)

    def send_image(self, image_path, caption="", chat_id=None):
        """Sends an image. If chat_id is not provided, broadcasts to all authorized chats."""
        targets = [str(chat_id)] if chat_id else self.chat_ids
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        
        if not os.path.exists(image_path):
            print(f"Image path does not exist: {image_path}")
            return False
            
        with open(image_path, "rb") as f:
            file_data = f.read()
            
        filename = os.path.basename(image_path)
        mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        
        all_success = True
        for target in targets:
            boundary = uuid.uuid4().hex
            body = bytearray()
            
            body.extend(f"--{boundary}\r\n".encode('utf-8'))
            body.extend(b"Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n")
            body.extend(f"{target}\r\n".encode('utf-8'))
            
            if caption:
                body.extend(f"--{boundary}\r\n".encode('utf-8'))
                body.extend(b"Content-Disposition: form-data; name=\"caption\"\r\n\r\n")
                body.extend(f"{caption}\r\n".encode('utf-8'))
                
            body.extend(f"--{boundary}\r\n".encode('utf-8'))
            body.extend(f"Content-Disposition: form-data; name=\"photo\"; filename=\"{filename}\"\r\n".encode('utf-8'))
            body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode('utf-8'))
            body.extend(file_data)
            body.extend(b"\r\n")
            body.extend(f"--{boundary}--\r\n".encode('utf-8'))
            
            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body))
            }
            
            try:
                req = urllib.request.Request(url, data=body, headers=headers)
                urllib.request.urlopen(req, timeout=15)
            except Exception as e:
                print(f"Failed to send telegram photo to {target}: {e}")
                all_success = False
        return all_success

    def send_document(self, file_path, caption="", chat_id=None):
        """Sends a document. If chat_id is not provided, broadcasts to all authorized chats."""
        targets = [str(chat_id)] if chat_id else self.chat_ids
        url = f"https://api.telegram.org/bot{self.bot_token}/sendDocument"
        
        if not os.path.exists(file_path):
            print(f"Document path does not exist: {file_path}")
            return False
            
        with open(file_path, "rb") as f:
            file_data = f.read()
            
        filename = os.path.basename(file_path)
        mime_type = 'application/octet-stream'
        
        all_success = True
        for target in targets:
            boundary = uuid.uuid4().hex
            body = bytearray()
            
            body.extend(f"--{boundary}\r\n".encode('utf-8'))
            body.extend(b"Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n")
            body.extend(f"{target}\r\n".encode('utf-8'))
            
            if caption:
                body.extend(f"--{boundary}\r\n".encode('utf-8'))
                body.extend(b"Content-Disposition: form-data; name=\"caption\"\r\n\r\n")
                body.extend(f"{caption}\r\n".encode('utf-8'))
                
            body.extend(f"--{boundary}\r\n".encode('utf-8'))
            body.extend(f"Content-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\n".encode('utf-8'))
            body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode('utf-8'))
            body.extend(file_data)
            body.extend(b"\r\n")
            body.extend(f"--{boundary}--\r\n".encode('utf-8'))
            
            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body))
            }
            
            try:
                req = urllib.request.Request(url, data=body, headers=headers)
                urllib.request.urlopen(req, timeout=15)
            except Exception as e:
                print(f"Failed to send telegram document to {target}: {e}")
                all_success = False
        return all_success
