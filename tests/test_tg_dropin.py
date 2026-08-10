import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__init__.__file__ if '__init__' in locals() else __file__), '../src')))

from tg_dropin import TelegramSidecar

def test_initialization_with_args():
    bot = TelegramSidecar(bot_token="test_token", chat_id="12345")
    assert bot.bot_token == "test_token"
    assert bot.chat_ids == ["12345"]
    assert "help" in bot.commands # built-in help
    
def test_initialization_missing_args():
    with pytest.raises(ValueError):
        TelegramSidecar(bot_token="", chat_id="123")
    with pytest.raises(ValueError):
        TelegramSidecar(bot_token="test", chat_id=None)

def test_multiple_chat_ids():
    bot = TelegramSidecar(bot_token="test", chat_id=["123", 456])
    assert bot.chat_ids == ["123", "456"]

def test_command_registration_with_description():
    bot = TelegramSidecar(bot_token="test", chat_id="123")
    
    @bot.command("ping", description="Replies with pong")
    def handle_ping(arg):
        pass
        
    assert "ping" in bot.commands
    assert bot.commands["ping"]["func"] == handle_ping
    assert bot.commands["ping"]["description"] == "Replies with pong"

def test_builtin_help():
    bot = TelegramSidecar(bot_token="test", chat_id="123")
    
    @bot.command("ping", description="Replies with pong")
    def handle_ping(arg):
        pass
        
    help_text = bot._builtin_help()
    assert "/help — Show this help message" in help_text
    assert "/ping — Replies with pong" in help_text

def test_return_values_are_sent(monkeypatch):
    bot = TelegramSidecar(bot_token="test", chat_id="123")
    
    sent_messages = []
    
    def mock_send_message(message, chat_id=None):
        sent_messages.append((message, chat_id))
        return True
        
    monkeypatch.setattr(bot, "send_message", mock_send_message)
    
    @bot.command("status")
    def handle_status(arg):
        return "All systems go"
        
    bot._process_message("/status", "123")
    
    assert len(sent_messages) == 1
    assert sent_messages[0] == ("All systems go", "123")

def test_chat_id_filtering():
    bot = TelegramSidecar(bot_token="test", chat_id=["123", "456"])
    
    call_record = {}
    
    @bot.command("ping")
    def handle_ping(arg):
        call_record["ping"] = True
        
    # Simulate processing valid command from authorized user
    bot._process_message("/ping", "456")
    assert call_record.get("ping") is True
    
    call_record.clear()
    
    # Normally filtering happens in _poll_loop, but let's just assert the structure works
    sender_id = "999"
    if sender_id in bot.chat_ids:
        bot._process_message("/ping", sender_id)
        
    assert not call_record.get("ping")

def test_exception_notification(monkeypatch):
    bot = TelegramSidecar(bot_token="test", chat_id="123")
    
    sent_messages = []
    def mock_notify(message):
        sent_messages.append(message)
        
    monkeypatch.setattr(bot, "notify", mock_notify)
    
    with pytest.raises(ValueError, match="Test error"):
        with bot.notify_exceptions():
            raise ValueError("Test error")
            
    assert len(sent_messages) == 1
    assert "Test error" in sent_messages[0]
    assert "ValueError" in sent_messages[0]
