"""
Scheduler de tareas.
Cada minuto revisa si hay tareas programadas para enviar al grupo de Telegram.
"""

import logging
from datetime import datetime
from telegram import Bot
from telegram.ext import ContextTypes

import database as db
from config import GROUP_CHAT_ID, PROJECT_NAME

logger = logging.getLogger(__name__)


async def check_and_send_tasks(context: ContextTypes.DEFAULT_TYPE):
    """Job que corre cada minuto para enviar tareas programadas."""
    pending = db.get_pending_scheduled_tasks()
    if not pending:
        return

    for task in pending:
        try:
            bot_username = (await context.bot.get_me()).username
            url_line = f"\n\n🔗 Enlace: {task['target_url']}" if task.get("target_url") else ""
            text = (
                f"📢 Nueva Tarea — {PROJECT_NAME}!\n\n"
                f"📌 {task['title']}\n\n"
                f"{task['description']}\n\n"
                f"📋 ¿Cómo completarla?\n"
                f"{task['instructions']}"
                f"{url_line}\n\n"
                f"💰 Vale: {task['points_value']} puntos\n\n"
                f"✅ Cuando termines, envía el screenshot al bot en privado:\n"
                f"👉 @{bot_username}"
            )
            msg = await context.bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=text
            )
            db.mark_scheduled_sent(task["id"], msg.message_id)
            logger.info(f"Tarea enviada al grupo: {task['title']} (sched_id={task['id']})")
        except Exception as e:
            logger.error(f"Error enviando tarea {task['id']}: {e}")


def setup_scheduler(app):
    """Registra el job de verificación en la cola de jobs de PTB."""
    app.job_queue.run_repeating(
        check_and_send_tasks,
        interval=60,   # cada 60 segundos
        first=10       # primera ejecución 10 segundos después del arranque
    )
    logger.info("Scheduler de tareas iniciado (intervalo: 60s)")
