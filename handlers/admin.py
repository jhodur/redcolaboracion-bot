"""
Handlers para el administrador del bot.
Comandos disponibles solo para IDs en ADMIN_IDS.
"""

import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters
)

import database as db
from config import ADMIN_IDS, PROJECT_NAME

# Estados de conversación
(
    TASK_ALLY, TASK_TITLE, TASK_DESC, TASK_INSTRUCTIONS, TASK_URL, TASK_POINTS,
    SCHEDULE_PICK_TASK, SCHEDULE_DATETIME,
    REWARD_NAME, REWARD_DESC, REWARD_POINTS, REWARD_PROVIDER,
) = range(12)


def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in ADMIN_IDS:
            await update.message.reply_text("⛔ No tienes permisos de administrador.")
            return ConversationHandler.END
        return await func(update, context)
    wrapper.__name__ = func.__name__
    return wrapper


# ─── Panel principal ──────────────────────────────────────────────────────────

@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"🛠️ *Panel de Administración — {PROJECT_NAME}*\n\n"
        "Comandos disponibles:\n\n"
        "📋 *Tareas*\n"
        "/nueva\\_tarea — Crear una nueva tarea\n"
        "/listar\\_tareas — Ver todas las tareas activas\n"
        "/programar — Programar envío de una tarea al grupo\n"
        "/proximos\\_envios — Ver próximos envíos programados\n\n"
        "🎁 *Premios*\n"
        "/nuevo\\_premio — Agregar un premio al catálogo\n"
        "/listar\\_premios — Ver catálogo de premios\n\n"
        "✅ *Validaciones*\n"
        "/pendientes — Ver comprobantes pendientes de revisión\n\n"
        "📊 *Estadísticas*\n"
        "/ranking — Ver ranking de usuarios por puntos\n"
        "/validar\\_codigo — Verificar un código de canje\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─── Crear tarea (conversación) ───────────────────────────────────────────────

@admin_only
async def nueva_tarea_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    allies = db.list_allies(status="approved")
    if not allies:
        await update.message.reply_text(
            "⚠️ No hay empresas aprobadas. Primero registra y aprueba una empresa."
        )
        return ConversationHandler.END

    lines = ["📝 *Nueva Tarea — Paso 1/6*\n\nSelecciona la *empresa* asociada:\n"]
    for a in allies:
        lines.append(f"🏢 ID `{a['id']}` — *{a['business_name']}* ({a['city'] or ''})")
    lines.append("\nEscribe el *ID* de la empresa:")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    return TASK_ALLY


async def task_ally(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ally_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ Escribe un número de ID válido.")
        return TASK_ALLY
    ally = db.get_ally(ally_id)
    if not ally:
        await update.message.reply_text("⚠️ Esa empresa no existe. Intenta con otro ID.")
        return TASK_ALLY
    context.user_data["ally_id"] = ally_id
    context.user_data["ally_name"] = ally["business_name"]
    await update.message.reply_text(
        f"🏢 Empresa: *{ally['business_name']}*\n\n"
        "📝 *Paso 2/6*\n\nEscribe el *título* de la tarea:",
        parse_mode="Markdown"
    )
    return TASK_TITLE


async def task_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["task_title"] = update.message.text.strip()
    await update.message.reply_text(
        "📝 *Paso 3/6*\n\nEscribe la *descripción breve* de la tarea "
        "(qué deben hacer los usuarios):",
        parse_mode="Markdown"
    )
    return TASK_DESC


async def task_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["task_desc"] = update.message.text.strip()
    await update.message.reply_text(
        "📝 *Paso 4/6*\n\nEscribe las *instrucciones detalladas* paso a paso "
        "(cómo deben tomar el screenshot, qué debe aparecer en él):",
        parse_mode="Markdown"
    )
    return TASK_INSTRUCTIONS


async def task_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["task_instructions"] = update.message.text.strip()
    await update.message.reply_text(
        "📝 *Paso 5/6*\n\nPega el *URL* de la publicación/página objetivo "
        "(o escribe `ninguno` si no aplica):",
        parse_mode="Markdown"
    )
    return TASK_URL


async def task_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    context.user_data["task_url"] = None if url.lower() == "ninguno" else url
    await update.message.reply_text(
        "📝 *Paso 6/6*\n\n¿Cuántos *puntos* vale completar esta tarea? "
        "(escribe un número, ej: 10):",
        parse_mode="Markdown"
    )
    return TASK_POINTS


async def task_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        points = int(update.message.text.strip())
        if points <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Por favor escribe un número válido mayor a 0.")
        return TASK_POINTS

    data = context.user_data
    task_id = db.create_task(
        title=data["task_title"],
        description=data["task_desc"],
        instructions=data["task_instructions"],
        target_url=data.get("task_url"),
        points_value=points,
        created_by=update.effective_user.id,
        ally_id=data.get("ally_id")
    )
    await update.message.reply_text(
        f"✅ *Tarea creada exitosamente* (ID: `{task_id}`)\n\n"
        f"📌 **{data['task_title']}**\n"
        f"🏢 Empresa: {data.get('ally_name', '-')}\n"
        f"💰 Puntos: {points}\n\n"
        "Usa /programar para enviarla al grupo.",
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Operación cancelada.")
    return ConversationHandler.END


# ─── Listar tareas ────────────────────────────────────────────────────────────

@admin_only
async def listar_tareas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = db.list_tasks()
    if not tasks:
        await update.message.reply_text("No hay tareas activas.")
        return

    lines = ["📋 *Tareas activas:*\n"]
    for t in tasks:
        url_info = f"\n   🔗 {t['target_url']}" if t["target_url"] else ""
        lines.append(
            f"• ID `{t['id']}` — *{t['title']}*\n"
            f"   💰 {t['points_value']} pts{url_info}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── Programar tarea (simple, sin botones inline) ─────────────────────────────

@admin_only
async def programar_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Uso: /programar o /programar <id>"""
    tasks = db.list_tasks()
    if not tasks:
        await update.message.reply_text("No hay tareas activas para programar.")
        return

    args = context.args
    if args and args[0].isdigit():
        # Envío directo: /programar 2
        task_id = int(args[0])
        task = db.get_task(task_id)
        if not task:
            await update.message.reply_text(f"❌ No existe la tarea con ID {task_id}.")
            return
        send_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.schedule_task(task_id, send_at)
        await update.message.reply_text(
            f"✅ Tarea programada para envio inmediato!\n\n"
            f"📌 {task['title']}\n"
            f"💰 {task['points_value']} puntos\n\n"
            "Aparecera en el canal en maximo 60 segundos.",
        )
        return

    # Mostrar lista para que elija
    lines = ["📅 *Tareas disponibles para programar:*\n"]
    for t in tasks:
        lines.append(f"📌 ID `{t['id']}` — *{t['title']}* ({t['points_value']} pts)")
    lines.append("\nPara enviar una tarea escribe:\n`/programar ID`\n\nEjemplo: `/programar 2`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── Próximos envíos ──────────────────────────────────────────────────────────

@admin_only
async def proximos_envios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = db.list_upcoming_scheduled()
    if not items:
        await update.message.reply_text("No hay envíos programados.")
        return
    lines = ["📅 *Últimos envíos programados:*\n"]
    for it in items:
        status = "✅ Enviado" if it["sent"] else "⏳ Pendiente"
        lines.append(
            f"• `{it['id']}` — {it['title']}\n"
            f"  {it['send_at']} — {status}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── Crear premio (conversación) ─────────────────────────────────────────────

@admin_only
async def nuevo_premio_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🎁 *Nuevo Premio — Paso 1/4*\n\nEscribe el *nombre* del premio:",
        parse_mode="Markdown"
    )
    return REWARD_NAME


async def reward_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["reward_name"] = update.message.text.strip()
    await update.message.reply_text(
        "🎁 *Paso 2/4*\n\nEscribe la *descripción* del premio "
        "(qué incluye, condiciones):",
        parse_mode="Markdown"
    )
    return REWARD_DESC


async def reward_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["reward_desc"] = update.message.text.strip()
    await update.message.reply_text(
        "🎁 *Paso 3/4*\n\n¿Cuántos *puntos* se necesitan para canjear este premio?",
        parse_mode="Markdown"
    )
    return REWARD_POINTS


async def reward_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pts = int(update.message.text.strip())
        if pts <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Escribe un número válido mayor a 0.")
        return REWARD_POINTS
    context.user_data["reward_points"] = pts
    await update.message.reply_text(
        "🎁 *Paso 4/4*\n\nEscribe el nombre del *proveedor/aliado* "
        "que ofrece este premio:",
        parse_mode="Markdown"
    )
    return REWARD_PROVIDER


async def reward_provider(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data
    reward_id = db.create_reward(
        name=data["reward_name"],
        description=data["reward_desc"],
        points_required=data["reward_points"],
        provider=update.message.text.strip()
    )
    await update.message.reply_text(
        f"✅ *Premio creado* (ID: `{reward_id}`)\n\n"
        f"🎁 {data['reward_name']}\n"
        f"💰 {data['reward_points']} puntos\n"
        f"🏢 {update.message.text.strip()}",
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END


# ─── Listar premios ───────────────────────────────────────────────────────────

@admin_only
async def listar_premios_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rewards = db.list_rewards(active_only=False)
    if not rewards:
        await update.message.reply_text("No hay premios registrados.")
        return
    lines = ["🎁 *Catálogo de Premios:*\n"]
    for r in rewards:
        estado = "✅" if r["is_active"] else "❌"
        lines.append(
            f"{estado} ID `{r['id']}` — *{r['name']}*\n"
            f"   💰 {r['points_required']} pts | 🏢 {r['provider']}\n"
            f"   _{r['description']}_"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── Pendientes de validación ─────────────────────────────────────────────────

@admin_only
async def ver_pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from validator import validate_screenshot
    pending = db.get_pending_completions()
    if not pending:
        await update.message.reply_text("✅ No hay comprobantes pendientes.")
        return
    await update.message.reply_text(
        f"⏳ *{len(pending)} comprobante(s) pendiente(s)*\n\n"
        "Procesando con IA...",
        parse_mode="Markdown"
    )
    for p in pending[:5]:  # procesar los primeros 5
        await validate_screenshot(context.bot, p)


# ─── Ranking ──────────────────────────────────────────────────────────────────

@admin_only
async def ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leaders = db.get_leaderboard(10)
    if not leaders:
        await update.message.reply_text("No hay usuarios registrados aún.")
        return
    lines = [f"🏆 *Ranking — {PROJECT_NAME}*\n"]
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    for i, u in enumerate(leaders):
        name = u["full_name"] or u["username"] or f"User {u['user_id']}"
        lines.append(f"{medals[i]} {name} — *{u['points']} pts*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── Validar código de canje ──────────────────────────────────────────────────

@admin_only
async def validar_codigo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 Escribe el *código del voucher* a verificar:",
        parse_mode="Markdown"
    )
    context.user_data["waiting_code"] = True


async def validar_codigo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting_code"):
        return
    code = update.message.text.strip().upper()
    redemption = db.get_redemption_by_code(code)
    context.user_data.pop("waiting_code", None)
    if not redemption:
        await update.message.reply_text(f"❌ Código `{code}` no encontrado.", parse_mode="Markdown")
        return
    status_emoji = "✅" if redemption["status"] == "active" else "🔴"
    used_info = f"\n📅 Usado: {redemption['used_at']}" if redemption["used_at"] else ""
    await update.message.reply_text(
        f"{status_emoji} *Voucher: {code}*\n\n"
        f"👤 {redemption['full_name']}\n"
        f"🎁 {redemption['reward_name']}\n"
        f"🏢 {redemption['provider']}\n"
        f"💰 {redemption['points_used']} puntos\n"
        f"📅 Generado: {redemption['redeemed_at']}{used_info}\n"
        f"Estado: {redemption['status'].upper()}",
        parse_mode="Markdown"
    )
    if redemption["status"] == "active":
        keyboard = [[InlineKeyboardButton("✅ Marcar como USADO", callback_data=f"use_voucher_{code}")]]
        await update.message.reply_text(
            "¿Deseas marcar este voucher como utilizado?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def mark_voucher_used_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in ADMIN_IDS:
        return
    code = query.data.replace("use_voucher_", "")
    db.mark_voucher_used(code)
    await query.edit_message_text(f"✅ Voucher `{code}` marcado como utilizado.", parse_mode="Markdown")


# ─── Registro de handlers ─────────────────────────────────────────────────────

def register(app):
    from telegram.ext import filters as f

    # Conversación: Nueva tarea
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("nueva_tarea", nueva_tarea_start)],
        states={
            TASK_ALLY:         [MessageHandler(f.TEXT & ~f.COMMAND, task_ally)],
            TASK_TITLE:        [MessageHandler(f.TEXT & ~f.COMMAND, task_title)],
            TASK_DESC:         [MessageHandler(f.TEXT & ~f.COMMAND, task_desc)],
            TASK_INSTRUCTIONS: [MessageHandler(f.TEXT & ~f.COMMAND, task_instructions)],
            TASK_URL:          [MessageHandler(f.TEXT & ~f.COMMAND, task_url)],
            TASK_POINTS:       [MessageHandler(f.TEXT & ~f.COMMAND, task_points)],
        },
        fallbacks=[CommandHandler("cancelar", cancel)],
        name="nueva_tarea"
    ))

    # Programar tarea: /programar o /programar <id>
    app.add_handler(CommandHandler("programar", programar_start))

    # Conversación: Nuevo premio
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("nuevo_premio", nuevo_premio_start)],
        states={
            REWARD_NAME:     [MessageHandler(f.TEXT & ~f.COMMAND, reward_name)],
            REWARD_DESC:     [MessageHandler(f.TEXT & ~f.COMMAND, reward_desc)],
            REWARD_POINTS:   [MessageHandler(f.TEXT & ~f.COMMAND, reward_points)],
            REWARD_PROVIDER: [MessageHandler(f.TEXT & ~f.COMMAND, reward_provider)],
        },
        fallbacks=[CommandHandler("cancelar", cancel)],
        name="nuevo_premio"
    ))

    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("listar_tareas", listar_tareas))
    app.add_handler(CommandHandler("proximos_envios", proximos_envios))
    app.add_handler(CommandHandler("listar_premios", listar_premios_admin))
    app.add_handler(CommandHandler("pendientes", ver_pendientes))
    app.add_handler(CommandHandler("ranking", ranking))
    app.add_handler(CommandHandler("validar_codigo", validar_codigo_start))
    app.add_handler(CallbackQueryHandler(mark_voucher_used_callback, pattern=r"^use_voucher_"))
    app.add_handler(MessageHandler(
        f.TEXT & ~f.COMMAND & f.ChatType.PRIVATE,
        validar_codigo_input
    ), group=10)
