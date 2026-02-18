import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import load_config
from bot.handlers import admin, guest, start, user
from bot.handlers import reg
from bot.middlewares.auth import AuthMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()

    bot = Bot(token=config["token"])
    dp = Dispatcher(storage=MemoryStorage())

    dp["store_path"] = config["store_path"]
    dp["admin_ids"] = config["admin_ids"]
    dp["scripts_path"] = config["scripts_path"]
    dp["default_core_node"] = config["default_core_node"]

    dp.update.middleware(AuthMiddleware(
        store_path=config["store_path"],
        admin_ids=config["admin_ids"],
    ))

    dp.include_router(start.router)
    dp.include_router(reg.router)
    dp.include_router(admin.router)
    dp.include_router(user.router)
    dp.include_router(guest.router)

    logger.info("Bot starting (v0.1.0)...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
