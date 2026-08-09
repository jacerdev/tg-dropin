import os
import time
import json
import threading
import mimetypes
import uuid
import urllib.request
import urllib.parse
import urllib.error

class TelegramBot:
    def __init__(self, bot_token=None, chat_id=None):
        """
        Initializes the Telegram Bot.
        If bot_token or chat_id are not provided, it will attempt to read them from environment variables (BOT_TOKEN and CHAT_ID).
        """
        self.bot_token = bot_token or os.environ.get("BOT_TOKEN")
        self.chat_id = str(chat_id or os.environ.get("CHAT_ID", ""))
        self.commands = {}
        self.default_handler = None
        self._stop_event = threading.Event()
        self._thread = None
        self.offset = None
        
    def command(self, name):
        """
        Decorator to register a command handler.
        Example:
            @bot.command("ping")
            def ping(arg):
                bot.send_message("pong")
        """
        def decorator(func):
            self.commands[name.lower()] = func # commands are not case sensitive
            return func
        return decorator

    def set_default_handler(self, func):
        """
        Sets a fallback handler for any message that doesn't match a registered command.
        (The handler will receive the full text message).
        """
        self.default_handler = func
        return func

    def start(self, poll_interval=1.0):
        """
        Starts the background polling thread.
        """
        if not self.bot_token or not self.chat_id:
            print("Telegram credentials missing (BOT_TOKEN or CHAT_ID). Telegram remote control disabled.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, 
            args=(poll_interval,), 
            daemon=True, # the thread is killed when the main program exits
            name="TelegramBotPoller"
        )
        self._thread.start()
        print("Telegram bot polling started in background.")

    def stop(self):
        """
        Signals the polling thread to stop and waits for it to finish.
        """
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
                    
                    if text and sender_id == self.chat_id: # security: only process messages from my chat_id
                        self._process_message(text)
            except Exception as e:
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
                        self.offset = results[-1]["update_id"] + 1 # mark everything before this ID as read
                    return results
        except (urllib.error.URLError, TimeoutError):
            pass # timeout is expected for long polling
        except Exception:
            pass
        return []

    def _process_message(self, text):
        parts = text.split(maxsplit=1)
        if not parts:
            return
            
        cmd = parts[0].lstrip('/').lower() # no need for slash in the command
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in self.commands:
            try:
                self.commands[cmd](arg)
            except Exception as e:
                self.send_message(f"⚠️ Error executing command '{cmd}': {e}")
        elif self.default_handler:
            try:
                self.default_handler(text)
            except Exception as e:
                self.send_message(f"⚠️ Error in default handler: {e}")
        else:
            self.send_message(f"⚠️ Unknown command: {cmd}")

    def send_message(self, message):
        """Sends a text message to the configured chat_id."""
        if not self.bot_token or not self.chat_id:
            return False
            
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        data = urllib.parse.urlencode({'chat_id': self.chat_id, 'text': message}).encode('utf-8')
        
        try:
            req = urllib.request.Request(url, data=data)
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception as e:
            print(f"Failed to send telegram message: {e}")
            return False

    def send_photo(self, photo_path, caption=""):
        """Sends a photo to the configured chat_id"""
        if not self.bot_token or not self.chat_id:
            return False
            
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        boundary = uuid.uuid4().hex
        
        try:
            if not os.path.exists(photo_path):
                print(f"Photo path does not exist: {photo_path}")
                return False
                
            with open(photo_path, "rb") as f:
                file_data = f.read()
                
            filename = os.path.basename(photo_path)
            mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            
            body = bytearray()
            
            # add chat_id
            body.extend(f"--{boundary}\r\n".encode('utf-8'))
            body.extend(b"Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n")
            body.extend(f"{self.chat_id}\r\n".encode('utf-8'))
            
            # add caption
            if caption:
                body.extend(f"--{boundary}\r\n".encode('utf-8'))
                body.extend(b"Content-Disposition: form-data; name=\"caption\"\r\n\r\n")
                body.extend(f"{caption}\r\n".encode('utf-8'))
                
            # add photo
            body.extend(f"--{boundary}\r\n".encode('utf-8'))
            body.extend(f"Content-Disposition: form-data; name=\"photo\"; filename=\"{filename}\"\r\n".encode('utf-8'))
            body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode('utf-8'))
            body.extend(file_data)
            body.extend(b"\r\n")
            
            # end boundary
            body.extend(f"--{boundary}--\r\n".encode('utf-8'))
            
            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body))
            }
            
            req = urllib.request.Request(url, data=body, headers=headers)
            urllib.request.urlopen(req, timeout=15)
            return True
        except Exception as e:
            print(f"Failed to send telegram photo: {e}")
            return False

    def send_document(self, file_path, caption=""):
        """Sends a document to the configured chat_id"""
        if not self.bot_token or not self.chat_id:
            return False
            
        url = f"https://api.telegram.org/bot{self.bot_token}/sendDocument"
        boundary = uuid.uuid4().hex
        
        try:
            if not os.path.exists(file_path):
                print(f"Document path does not exist: {file_path}")
                return False
                
            with open(file_path, "rb") as f:
                file_data = f.read()
                
            filename = os.path.basename(file_path)
            mime_type = 'application/octet-stream' # Default for unknown documents
            
            body = bytearray()
            
            # add chat_id
            body.extend(f"--{boundary}\r\n".encode('utf-8'))
            body.extend(b"Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n")
            body.extend(f"{self.chat_id}\r\n".encode('utf-8'))
            
            # add caption
            if caption:
                body.extend(f"--{boundary}\r\n".encode('utf-8'))
                body.extend(b"Content-Disposition: form-data; name=\"caption\"\r\n\r\n")
                body.extend(f"{caption}\r\n".encode('utf-8'))
                
            #add document
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
            
            req = urllib.request.Request(url, data=body, headers=headers)
            urllib.request.urlopen(req, timeout=15)
            return True
        except Exception as e:
            print(f"Failed to send telegram document: {e}")
            return False
