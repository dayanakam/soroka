"""Точка входа: веб-сервер с мини-аппом, бот на long polling и расписание."""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import config, db
from .bot import dp, make_bot, send_digest
from .server import start_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("outfits")


async def weekly(bot) -> None:
    chats = db.all_active_chats()
    log.info("еженедельный дайджест: %s получателей", len(chats))
    for chat_id in chats:
        try:
            await send_digest(bot, chat_id)
        except Exception as e:
            log.exception("дайджест для %s упал: %s", chat_id, e)
        await asyncio.sleep(1)
    db.prune_seen()


async def drops(bot) -> None:
    chats = db.all_active_chats()
    for chat_id in chats:
        try:
            await send_digest(bot, chat_id, n=3, only_drops=True)
        except Exception as e:
            log.exception("проверка скидок для %s упала: %s", chat_id, e)
        await asyncio.sleep(1)


async def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit(
            "Нет BOT_TOKEN. Создай бота у @BotFather, скопируй .env.example в .env "
            "и впиши токен."
        )
    if config.app_url():
        log.info("анкета: %s", config.app_url())
    else:
        log.warning("адрес анкеты не задан — кнопка «Мой вкус» запустит опрос в чате")

    db.init()
    runner = await start_server()
    bot = await make_bot()

    sched = AsyncIOScheduler(timezone=config.TZ)
    sched.add_job(weekly, "cron", day_of_week=config.DIGEST_DAY,
                  hour=config.DIGEST_HOUR, minute=0, args=[bot], id="weekly")
    sched.add_job(drops, "interval", hours=config.DROPS_HOURS, args=[bot], id="drops")
    sched.start()
    log.info("расписание: дайджест %s в %s:00, скидки каждые %sч (%s)",
             config.DIGEST_DAY, config.DIGEST_HOUR, config.DROPS_HOURS, config.TZ)

    try:
        await dp.start_polling(bot, handle_signals=False)
    finally:
        sched.shutdown(wait=False)
        await bot.session.close()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        if str(e):
            print(e)
