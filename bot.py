import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from handlers.admin import admin_router
from handlers.user import user_router
import database.db_helper as db

# Configure logging
logging.basicConfig(level=logging.INFO)

async def main():
    # Initialize SQLite tables
    db.init_db()
    
    if not BOT_TOKEN:
        print("CRITICAL DIRECTIVE MISSING: 'BOT_TOKEN' environment variable unset inside config!")
        return

    # Initialize BOT and Dispatcher
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    # Register routers
    dp.include_router(admin_router)
    dp.include_router(user_router)
    
    # Start long polling
    print("🚀 Telegram OMR Test Checker Bot started successfully! Awaiting requests...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🤖 Bot stopped.")
