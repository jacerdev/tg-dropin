# TG-DropIn: Zero-Dependency Telegram Sidecar

> **Status:** Early release (`0.1.x`). The API may change before `1.0`.

**Add Telegram remote control to any Python script — without rewriting it as a bot.**

`tg-dropin` is a zero-dependency Telegram sidecar for long-running scripts, research experiments, training jobs, data pipelines, and automation. It runs in a background thread, leaving your existing synchronous code untouched.

Unlike major bot frameworks that hijack main loops or force you to rewrite code using `asyncio`, this module spins up a background daemon thread using built-in `threading` and `urllib`. This sidecar approach lets heavy, synchronous tasks run completely uninterrupted.

## Features
- **Zero Dependencies:** Uses only standard library modules.
- **Non-blocking:** Runs gracefully in the background, out of the way of your main script.
- **Auto-Generated `/help`:** Add descriptions to your commands, and the bot generates a help menu automatically.
- **Exception Notifications:** Wrap your code in a context manager to instantly get tracebacks sent to your phone if it crashes.
- **Security Whitelisting:** Only processes messages from your explicitly specified `CHAT_ID` (or list of IDs).
- **Media Support:** Built-in `notify`, `send_file`, `send_image`, and `send_document` utility methods.

## Installation

There are two ways to use `tg-dropin`.

**Method 1: Install via pip**
```bash
pip install tg-dropin
```

**Method 2: The "Drop-In" approach (Zero Installation)**
Because it has zero dependencies, you can simply copy the `src/tg_dropin.py` file directly into your project directory and use it immediately.

## Quickstart

```python
import time
from tg_dropin import TelegramSidecar

# Initialize bot with credentials
bot = TelegramSidecar(bot_token="YOUR_BOT_TOKEN", chat_id=["USER_1_ID", "USER_2_ID"])

# (optional) Register commands with descriptions for the auto-generated /help menu
@bot.command("ping", description="Check if the script is still alive")
def handle_ping(arg):
    return f"pong! You sent: ping {arg}" # Handlers can simply return a string to automatically send it back.

# Fallback handler for unmatched messages
@bot.set_default_handler
def handle_unknown(text):
    return f"Unknown command: {text}"

# Use the bot as a Context Manager to automatically start and stop the background thread (or use bot.start() / bot.stop())
with bot:
    
    bot.notify("🚀 Script has started!")  # Broadcasts to all authorized chats
    bot.send_message("Targeted message", chat_id="USER_1_ID") # Or send to a specific chat
    
   
    with bot.notify_exceptions(): # (optional) Wrap code to send tracebacks to Telegram if it crashes
        
        # Send files easily
        # bot.send_file("plot.png", caption="Training loss")
        
        while True:
            # Main synchronous workload
            time.sleep(1)

# On exit, the bot stops polling cleanly.
```

## Setup Telegram Bot
1. Go to Telegram and message `@BotFather`.
2. Use `/newbot` to create a new bot and get a token.
3. To get your Chat ID, send a message to your new bot, then visit:
   `https://api.telegram.org/bot<YourBOTToken>/getUpdates`
   Look for `"chat":{"id":123456789}` in the response.

## Bonus: Bash / CLI Usage

If you want to send notifications directly from your shell scripts, you can add this helper function to your `.bashrc` or script. 

```bash
send_telegram_message() {
    export BOT_TOKEN="your_bot_token"
    export CHAT_ID="your_chat_id"
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${CHAT_ID}" \
        --data-urlencode "text=$1" > /dev/null
    
    echo "📣: $1" # prints the message to the terminal
}

# Example usage:
# python train.py && send_telegram_message "Training finished successfully!"
```
