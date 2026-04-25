"""
Punto de entrada principal del bot de gamificación de Telegram.
"""

import logging
import sys
from telegram.ext import Application

import database as db
from config import BOT_TOKEN, PROJECT_NAME
from scheduler import setup_scheduler
from auto_scheduler import setup_auto_scheduler
import handlers.admin as admin_handlers
import handlers.user as user_handlers

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN no configurado. Edita el archivo .env")
        sys.exit(1)

    logger.info(f"Iniciando bot — {PROJECT_NAME}")

    # Inicializar base de datos
    db.init_db()
    logger.info("Base de datos inicializada")

    # Crear aplicación
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Registrar handlers (users primero para que /start funcione)
    user_handlers.register(app)
    admin_handlers.register(app)

    # Error handler global
    async def error_handler(update, context):
        logger.error(f"Error: {context.error}", exc_info=context.error)
    app.add_error_handler(error_handler)

    # Iniciar scheduler de tareas
    setup_scheduler(app)
    setup_auto_scheduler(app)

    logger.info("Bot en funcionamiento. Presiona Ctrl+C para detener.")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"]
    )


if __name__ == "__main__":
    main()
