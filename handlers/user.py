"""
Handlers para usuarios del grupo.
Completar tareas, ver puntos, canjear premios.
"""

import os
import logging
import secrets
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler,
    MessageHandler, CallbackQueryHandler, ChatMemberHandler, filters
)

logger = logging.getLogger(__name__)

import database as db
from config import PROJECT_NAME, BOT_TOKEN
from voucher import generate_voucher

BOT_USERNAME = None

SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


def _ensure_user(update: Update):
    user = update.effective_user
    db.upsert_user(user.id, user.username or "", user.full_name or user.first_name or "")
    return db.get_user(user.id)


# ─── /start ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _ensure_user(update)

    # Deep-link: /start redeem_<id>
    if context.args and context.args[0].startswith("redeem_"):
        await _process_redeem(update, context, context.args[0])
        return

    # Deep-link: /start shop_<provider>
    if context.args and context.args[0].startswith("shop_"):
        provider_name = context.args[0][5:].replace("_", " ")
        context.args = [provider_name]
        await canjear_start(update, context)
        return

    name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 ¡Hola, {name}! Bienvenido/a a *{PROJECT_NAME}*\n\n"
        "Aquí puedes completar tareas, acumular puntos y canjearlos por premios.\n\n"
        "📌 *Comandos disponibles:*\n"
        "/tareas — Ver tareas activas\n"
        "/mis\\_puntos — Ver tu saldo de puntos\n"
        "/premios — Ver catálogo de premios\n"
        "/canjear — Canjear puntos por un premio\n"
        "/mis\\_canjes — Ver tus canjes anteriores\n"
        "/historial — Ver tus últimas tareas\n\n"
        "Para completar una tarea, envíame el screenshot como foto en este chat.",
        parse_mode="Markdown"
    )


# ─── /mis_puntos ─────────────────────────────────────────────────────────────

async def mis_puntos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _ensure_user(update)
    completions = db.get_user_completions(user["user_id"], limit=3)
    recent = ""
    if completions:
        recent = "\n\n📋 *Últimas actividades:*"
        for c in completions:
            emoji = "✅" if c["status"] == "approved" else ("⏳" if c["status"] == "pending" else "❌")
            pts = f"+{c['points_awarded']} pts" if c["status"] == "approved" else ""
            recent += f"\n{emoji} {c['title']} {pts}"
    await update.message.reply_text(
        f"💰 *Tus puntos — {PROJECT_NAME}*\n\n"
        f"👤 {user['full_name']}\n"
        f"⭐ Puntos acumulados: *{user['points']}*{recent}",
        parse_mode="Markdown"
    )


# ─── /historial ──────────────────────────────────────────────────────────────

async def historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _ensure_user(update)
    completions = db.get_user_completions(user["user_id"], limit=10)
    if not completions:
        await update.message.reply_text("No has completado ninguna tarea todavía.")
        return
    lines = ["📋 *Tu historial de tareas:*\n"]
    for c in completions:
        emoji = {"approved": "✅", "pending": "⏳", "rejected": "❌"}.get(c["status"], "❓")
        pts = f" (+{c['points_awarded']} pts)" if c["status"] == "approved" else ""
        date = c["submitted_at"][:10]
        lines.append(f"{emoji} {c['title']}{pts}\n   📅 {date}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── /premios ────────────────────────────────────────────────────────────────

async def ver_premios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _ensure_user(update)
    products = db.list_redeemable_products()
    if not products:
        await update.message.reply_text("No hay premios disponibles por el momento.")
        return
    lines = [
        f"🎁 *Catálogo de Premios — {PROJECT_NAME}*\n",
        f"💰 Tus puntos: *{user['points']}*\n"
    ]
    for r in products:
        can = "✅" if user["points"] >= r["points_required"] else "🔒"
        lines.append(
            f"{can} *{r['name']}*\n"
            f"   💰 {r['points_required']} pts | 🏢 {r['provider']}"
        )
    lines.append("\nUsa /canjear para redimir tus puntos.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── Lógica de canje ────────────────────────────────────────────────────────

async def _process_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE, param: str):
    """Procesa el canje de un producto. param = 'redeem_<id>' o '<id>'."""
    user_id = update.effective_user.id
    logger.info(f"[REDEEM] Inicio user={user_id} param={param}")

    product_id_str = param.replace("redeem_", "")
    if not product_id_str.isdigit():
        logger.warning(f"[REDEEM] Param no numerico: {param}")
        await update.message.reply_text("❌ Producto no válido.")
        return

    product_id = int(product_id_str)
    user = db.get_user(user_id)
    product = db.get_product(product_id)
    logger.info(f"[REDEEM] product_id={product_id} found={product is not None}")

    if not product or not product["is_active"] or product["points_required"] <= 0:
        logger.warning(f"[REDEEM] Producto no disponible product={product}")
        await update.message.reply_text("❌ Ese producto no existe o no está disponible.")
        return
    if user["points"] < product["points_required"]:
        logger.info(f"[REDEEM] Sin puntos user_pts={user['points']} req={product['points_required']}")
        await update.message.reply_text(
            f"❌ No tienes suficientes puntos.\n"
            f"Necesitas: {product['points_required']} | Tienes: {user['points']}"
        )
        return

    success = db.subtract_points(user_id, product["points_required"])
    logger.info(f"[REDEEM] subtract_points success={success}")
    if not success:
        await update.message.reply_text("❌ Error al procesar el canje. Intenta de nuevo.")
        return

    voucher_code = secrets.token_hex(4).upper()
    db.create_redemption(user_id, product_id, product["points_required"], voucher_code)
    updated_user = db.get_user(user_id)
    logger.info(f"[REDEEM] Redemption creada code={voucher_code}")

    try:
        voucher_path = generate_voucher(
            user_name=user["full_name"],
            reward_name=product["name"],
            provider=product["provider"],
            points_used=product["points_required"],
            new_balance=updated_user["points"],
            voucher_code=voucher_code
        )
        logger.info(f"[REDEEM] Voucher generado: {voucher_path}")
    except Exception as e:
        logger.exception(f"[REDEEM] Error generando voucher: {e}")
        voucher_path = None

    await update.message.reply_text(
        f"✅ *¡Canje exitoso!*\n\n"
        f"🎁 {product['name']}\n"
        f"🏢 {product['provider']}\n"
        f"💰 Puntos usados: {product['points_required']}\n"
        f"⭐ Nuevo saldo: *{updated_user['points']} pts*\n\n"
        f"🎟️ Código: `{voucher_code}`\n\n"
        "Presenta este código al momento de usar tu premio.",
        parse_mode="Markdown"
    )

    if voucher_path and os.path.exists(voucher_path):
        try:
            with open(voucher_path, "rb") as f:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=f,
                    caption=f"🎟️ Tu comprobante de canje — Código: `{voucher_code}`",
                    parse_mode="Markdown"
                )
            logger.info(f"[REDEEM] Voucher enviado al usuario")
        except Exception as e:
            logger.exception(f"[REDEEM] Error enviando voucher photo: {e}")
    else:
        logger.warning(f"[REDEEM] Voucher path no existe: {voucher_path}")

    # Notificar al proveedor por Telegram
    try:
        await _notify_provider(context.bot, product, user, voucher_code)
    except Exception as e:
        logger.exception(f"[REDEEM] Error notificando provider: {e}")


async def _notify_provider(bot, product, user, voucher_code):
    """Envía notificación al contacto de Telegram del proveedor."""
    try:
        tg_user = product.get("telegram_user", "")
        if not tg_user:
            return

        tg_user = tg_user.lstrip("@")
        import sqlite3
        from config import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT user_id FROM users WHERE username = ?", (tg_user,)
        ).fetchone()
        conn.close()

        if row:
            await bot.send_message(
                chat_id=row["user_id"],
                text=(
                    f"🔔 *¡Nuevo canje en tu empresa!*\n\n"
                    f"👤 Cliente: {user['full_name']}\n"
                    f"🎁 Producto: {product['name']}\n"
                    f"💰 Puntos canjeados: {product['points_required']}\n"
                    f"🎟️ Código: `{voucher_code}`\n\n"
                    f"🏢 {product['provider']}\n\n"
                    "El cliente presentará este código para redimir su premio."
                ),
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.warning(f"No se pudo notificar al proveedor: {e}")


# ─── /canjear ────────────────────────────────────────────────────────────────

async def canjear_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_USERNAME
    user = _ensure_user(update)
    rewards = [r for r in db.list_redeemable_products() if user["points"] >= r["points_required"]]

    if not rewards:
        await update.message.reply_text(
            f"🔒 Necesitas más puntos para canjear.\n"
            f"💰 Tus puntos actuales: *{user['points']}*\n\n"
            "Completa más tareas para acumular puntos.",
            parse_mode="Markdown"
        )
        return

    args = context.args

    # /canjear <reward_id> → canjear directo
    if args and args[0].isdigit():
        await _process_redeem(update, context, args[0])
        return

    # /canjear <nombre_empresa> → mostrar premios de esa empresa con botones
    if args and not args[0].isdigit():
        provider_name = " ".join(args)
        provider_rewards = [r for r in rewards if r["provider"].lower() == provider_name.lower()]
        if not provider_rewards:
            await update.message.reply_text("❌ No hay premios disponibles en esta empresa para tus puntos.")
            return

        if not BOT_USERNAME:
            bot_info = await context.bot.get_me()
            BOT_USERNAME = bot_info.username

        keyboard = []
        for r in provider_rewards:
            keyboard.append([InlineKeyboardButton(
                f"🎁 {r['name']} — {r['points_required']} pts",
                url=f"https://t.me/{BOT_USERNAME}?start=redeem_{r['id']}"
            )])

        await update.message.reply_text(
            f"🏢 *{provider_rewards[0]['provider']}*\n\n"
            f"💰 Tus puntos: *{user['points']}*\n\n"
            "Selecciona el premio que deseas:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    # Por defecto: mostrar lista de empresas con botones
    if not BOT_USERNAME:
        bot_info = await context.bot.get_me()
        BOT_USERNAME = bot_info.username

    providers = {}
    for r in rewards:
        prov = r["provider"]
        if prov not in providers:
            providers[prov] = 0
        providers[prov] += 1

    keyboard = []
    for prov, count in providers.items():
        safe_name = prov.replace(" ", "_")
        keyboard.append([InlineKeyboardButton(
            f"🏢 {prov} ({count} premios)",
            url=f"https://t.me/{BOT_USERNAME}?start=shop_{safe_name}"
        )])

    await update.message.reply_text(
        f"🎁 *Canjear Puntos*\n\n"
        f"💰 Tus puntos: *{user['points']}*\n\n"
        "Selecciona la empresa donde quieres redimir:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ─── /mis_canjes ─────────────────────────────────────────────────────────────

async def mis_canjes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _ensure_user(update)
    redemptions = db.get_user_redemptions(user["user_id"])
    if not redemptions:
        await update.message.reply_text("No has realizado ningún canje todavía.")
        return
    lines = ["🎟️ *Tus canjes:*\n"]
    for r in redemptions:
        status_emoji = "✅" if r["status"] == "active" else "🔴"
        lines.append(
            f"{status_emoji} *{r['name']}* — {r['provider']}\n"
            f"   💰 {r['points_used']} pts | Código: `{r['voucher_code']}`\n"
            f"   📅 {r['redeemed_at'][:10]}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── Recibir screenshot ───────────────────────────────────────────────────────

async def receive_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """El usuario envía una foto como comprobante de tarea."""
    from validator import validate_and_award

    user = _ensure_user(update)

    # Verificar si hay tarea activa en el grupo
    pending_tasks = db.get_pending_scheduled_tasks()
    # Buscar la más reciente que ya fue enviada
    sent_tasks = [t for t in db.list_upcoming_scheduled() if t["sent"] == 1]

    if not sent_tasks:
        await update.message.reply_text(
            "⚠️ No hay tareas activas en este momento.\n"
            "Espera a que el administrador envíe una tarea al grupo."
        )
        return

    # Usar la tarea más reciente enviada
    latest = db.get_scheduled_task(sent_tasks[0]["id"])
    if not latest:
        await update.message.reply_text("⚠️ No se encontró la tarea activa.")
        return

    # Verificar si ya la completó
    if db.has_completed_task(user["user_id"], latest["id"]):
        await update.message.reply_text(
            "✅ Ya completaste esta tarea. ¡Espera la próxima!"
        )
        return

    # Descargar y guardar el screenshot
    photo = update.message.photo[-1]  # mayor resolución
    file = await photo.get_file()
    screenshot_path = os.path.join(
        SCREENSHOTS_DIR,
        f"{user['user_id']}_{latest['id']}_{int(datetime.now().timestamp())}.jpg"
    )
    await file.download_to_drive(screenshot_path)

    # Registrar envío pendiente
    completion_id = db.submit_completion(
        user_id=user["user_id"],
        task_id=latest["task_id"],
        scheduled_id=latest["id"],
        screenshot_path=screenshot_path
    )

    if completion_id is None:
        await update.message.reply_text(
            "⚠️ Ya enviaste un comprobante para esta tarea. Espera la validación."
        )
        return

    await update.message.reply_text(
        "📸 *Comprobante recibido*\n\n"
        "Tu screenshot está siendo validado con IA. "
        "Te notificaremos el resultado en breve. ⏳",
        parse_mode="Markdown"
    )

    # Validar con IA inmediatamente
    completion = db.get_completion(completion_id)
    await validate_and_award(context.bot, completion)


# ─── Bienvenida a nuevos miembros ─────────────────────────────────────────────

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Da la bienvenida cuando un nuevo usuario se une al grupo (new_chat_members)."""
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        await _send_welcome(context.bot, update.effective_chat.id, member)


async def welcome_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Da la bienvenida cuando alguien se une al canal/supergrupo (chat_member update)."""
    if update.chat_member is None:
        return
    old = update.chat_member.old_chat_member
    new = update.chat_member.new_chat_member
    # Detectar: no era miembro → ahora es miembro
    if old.status in ("left", "kicked") and new.status in ("member", "restricted"):
        member = new.user
        if member.is_bot:
            return
        await _send_welcome(context.bot, update.effective_chat.id, member)


async def _send_welcome(bot, chat_id, member):
    """Envía el mensaje de bienvenida."""
    db.upsert_user(member.id, member.username or "", member.full_name or member.first_name or "")
    name = member.first_name or member.full_name or "viajero"

    global BOT_USERNAME
    if not BOT_USERNAME:
        bot_info = await bot.get_me()
        BOT_USERNAME = bot_info.username

    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"👋 *¡Bienvenido/a, {name}!*\n\n"
            f"Has llegado a *{PROJECT_NAME}* — la red de turismo colaborativo.\n\n"
            "🎮 *¿Como funciona?*\n"
            "1️⃣ Publicamos tareas en este grupo (dar like, comentar, compartir)\n"
            "2️⃣ Completas la tarea y nos envias el screenshot al bot\n"
            "3️⃣ La IA valida tu screenshot y ganas puntos\n"
            "4️⃣ Canjeas tus puntos por premios reales en nuestras empresas aliadas\n\n"
            "💰 *Tabla de puntos:*\n"
            "• Me gusta / Compartir = 10 pts\n"
            "• Comentar = 15 pts\n"
            "• Desde 20 pts ya puedes canjear premios\n\n"
            f"📲 Escribe al bot @{BOT_USERNAME} en privado para comenzar.\n"
            "Usa /start para ver todos los comandos disponibles."
        ),
        parse_mode="Markdown"
    )


# ─── /tareas ─────────────────────────────────────────────────────────────────

async def ver_tareas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista tareas activas. /tareas → empresas con tareas; /tareas <empresa> → tareas de esa empresa."""
    import sqlite3
    from config import DB_PATH

    args = context.args
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Tareas activas (envíadas en las últimas 48h)
    sent_tasks = conn.execute("""
        SELECT st.id, st.send_at, t.id as task_id, t.title, t.description, t.instructions,
               t.target_url, t.points_value, t.ally_id,
               COALESCE(a.business_name, 'Sin empresa') as business_name
        FROM scheduled_tasks st
        JOIN tasks t ON t.id = st.task_id
        LEFT JOIN allies a ON a.id = t.ally_id
        WHERE st.sent = 1
          AND st.send_at >= datetime('now', '-48 hours')
          AND t.is_active = 1
        ORDER BY st.send_at DESC
    """).fetchall()
    conn.close()

    sent_tasks = [dict(t) for t in sent_tasks]
    if not sent_tasks:
        await update.message.reply_text(
            "No hay tareas activas en este momento. "
            "Mantente atento al grupo de Telegram."
        )
        return

    # Filtrar por empresa si se pasó argumento
    if args:
        provider_name = " ".join(args).lower()
        filtered = [t for t in sent_tasks if t["business_name"].lower() == provider_name]
        if not filtered:
            await update.message.reply_text(f"No hay tareas activas de '{provider_name}'.")
            return

        lines = [f"📌 *Tareas activas — {filtered[0]['business_name']}*\n"]
        for t in filtered:
            url_line = f"\n🔗 {t['target_url']}" if t.get("target_url") else ""
            lines.append(
                f"📌 *{t['title']}*\n"
                f"{t['description']}\n"
                f"📋 {t['instructions']}{url_line}\n"
                f"💰 *{t['points_value']} puntos*\n"
            )
        lines.append("\nEnvía el screenshot a este chat para validar.")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # Sin argumento: agrupar por empresa
    by_provider = {}
    for t in sent_tasks:
        by_provider.setdefault(t["business_name"], []).append(t)

    lines = ["📌 *Tareas activas por empresa:*\n"]
    for provider, tasks in by_provider.items():
        lines.append(f"🏢 *{provider}* ({len(tasks)} tareas)\n   👉 `/tareas {provider}`")
    lines.append("\n_Toca el comando para ver las tareas de esa empresa_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── Registro ────────────────────────────────────────────────────────────────

def register(app):
    from telegram.ext import filters as f

    # Canjear: /canjear o /canjear <id>
    app.add_handler(CommandHandler("canjear", canjear_start))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mis_puntos", mis_puntos))
    app.add_handler(CommandHandler("historial", historial))
    app.add_handler(CommandHandler("premios", ver_premios))
    app.add_handler(CommandHandler("mis_canjes", mis_canjes))
    app.add_handler(CommandHandler("tareas", ver_tareas))

    # Bienvenida a nuevos miembros (grupo: new_chat_members, canal: chat_member)
    app.add_handler(MessageHandler(
        f.StatusUpdate.NEW_CHAT_MEMBERS,
        welcome_new_member
    ))
    app.add_handler(ChatMemberHandler(
        welcome_chat_member,
        ChatMemberHandler.CHAT_MEMBER
    ))

    # Recibir screenshots solo en chat privado
    app.add_handler(MessageHandler(
        f.PHOTO & f.ChatType.PRIVATE,
        receive_screenshot
    ))
