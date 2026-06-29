import logging
import os

from telethon import TelegramClient

import config
from handlers import register_handlers

logger = logging.getLogger(__name__)

def main():
    # Verify configuration
    if not config.API_ID or not config.API_HASH or not config.BOT_TOKEN:
        logger.error(
            "Missing environment variables. Make sure TELEGRAM_API_ID, "
            "TELEGRAM_API_HASH, and TELEGRAM_BOT_TOKEN are set in your .env file."
        )
        return
        
    logger.info("Initializing Telethon Client...")
    os.makedirs('session', exist_ok=True)
    client = TelegramClient('session/bot', config.API_ID, config.API_HASH)
    
    # Register callback handlers
    register_handlers(client)
    
    logger.info("Starting bot client session...")
    client.start(bot_token=config.BOT_TOKEN)
    
    logger.info("Bot is active and running. Press Ctrl+C to stop.")
    client.run_until_disconnected()

if __name__ == "__main__":
    main()
