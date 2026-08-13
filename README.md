# TG-DropIn

A zero-dependency Telegram sidecar for Python scripts, providing notifications and remote control for long-running jobs without restructuring code or installing anything.

## Features
- **Zero Dependencies:** Uses only standard library modules.
- **Media Support:** Built-in `send_message` and `send_file`.
- **Exception Notifications:** Wrap code to receive tracebacks on crash.

## Installation

**Install via pip:**
```bash
pip install tg-dropin
```

**Or just drop it in literally:**
Copy-Paste `src/tg_dropin.py`.

## Quickstart

```python
from tg_dropin import TelegramSidecar

# Initialize bot with credentials
bot = TelegramSidecar(bot_token="BOT_TOKEN", chat_id=["USER_1_ID", "USER_2_ID"])

# Optional: Register commands with descriptions for the auto-generated /help menu
@bot.command("ping", description="Check if the script is still alive")
def handle_ping(arg):
    return f"pong! Received: ping {arg}" # Handlers that return a string automatically send replies

# Fallback handler for unmatched messages
@bot.set_default_handler
def handle_unknown(text):
    return f"Unknown command: {text}"

# Start the background daemon thread manually
bot.start()

bot.send_message("🚀 Script has started!")  # Broadcasts to all authorized chats or send to a specific chat

with bot.notify_exceptions(): # Optional: Wrap code to send tracebacks to Telegram in case of an exception
    
    # Main synchronous workload ...

bot.send_file("plot.png", caption="Training loss")

# bot.stop() # Optional: stop the bot gracefully (daemon threads exit automatically)
```

## Architecture & Concurrency

`tg-dropin` spawns two lightweight background daemon threads when `start()` is called:
1. **Poller Thread:** Continuously long-polls the Telegram API for new messages and drops them into a thread-safe queue. It never blocks.
2. **Worker Thread:** Reads messages from the queue and executes registered `@bot.command` handlers **sequentially**. 

> [!NOTE]
> Because handlers are executed sequentially on a single worker thread, a long-running handler will delay the processing of subsequent commands, but it will *not* block the Poller Thread from fetching new messages.

---

## Bonus: Bash / CLI Usage (Standalone)

For sending notifications directly from bash scripts without using this Python package:

```bash
send_telegram_message() {
    export BOT_TOKEN="bot_token"
    export CHAT_ID="chat_id"
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${CHAT_ID}" \
        --data-urlencode "text=$1" > /dev/null
    echo "📣: $1" # prints the message to the terminal
}
# Example usage:
# python train.py && send_telegram_message "Training finished successfully!"
```

## Appendix: Setup Telegram Bot
1. Open Telegram and message `@BotFather`.
2. Use `/newbot` to create a bot and get a token.
3. To get the Chat ID, send a message to the bot, then visit:
   `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates`
   Look for `"chat":{"id":123456789}` in the response.
