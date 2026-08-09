# tg-dropin: Zero-Dependency Telegram Sidecar

A lightweight, zero-dependency Telegram remote-control module designed as a true drop-in for existing Python scripts.

Unlike major bot frameworks that hijack main loops or force you to rewrite code using `asyncio`, this module spins up a background daemon thread using built-in `threading` and `urllib`. This sidecar approach lets heavy, synchronous tasks run completely uninterrupted.

## Features
- **Zero Dependencies:** Uses only standard library modules. No need for `pip install`.
- **Non-blocking:** Runs gracefully in the background, out of the way of your main script.
- **Simple Decorator API:** Map Telegram commands to backend functions easily.
- **Security Whitelisting:** Only processes messages from your specified `CHAT_ID`.
- **Media Support:** Built-in `send_message`, `send_photo`, and `send_document` utility methods.

## Quickstart

Just copy `telegram_bot.py` into your project directory.

```python
import time
from telegram_bot import TelegramBot

# Initialize bot (pass credentials directly or leave empty to use env variables)
bot = TelegramBot(bot_token="your_bot_token", chat_id="your_chat_id")

# Send outbound notifications (works anytime)
bot.send_message("🚀 Script has started!")
# bot.send_photo("plot.png", caption="Training loss")
# bot.send_document("logs.txt", caption="Full log")

# Register remote commands and start the background listener (optional)
@bot.command("ping")
def handle_ping(arg):
    bot.send_message(f"pong! (arg: {arg})")

@bot.set_default_handler
def handle_unknown(text):
    bot.send_message(f"Unknown command: {text}")

bot.start()

# Your main synchronous workload
print("Main program is running...")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    bot.stop() # does nothing if bot.start() was not called
    print("Exiting...")
```

## Setup Telegram Bot
1. Go to Telegram and message `@BotFather`.
2. Use `/newbot` to create a new bot and get a token.
3. Message `IDBot` or use a similar service to find out your personal Chat ID.
4. Set the `BOT_TOKEN` and `CHAT_ID` environment variables.

```bash
export BOT_TOKEN="your_bot_token"
export CHAT_ID="your_chat_id"
```
