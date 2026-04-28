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
        f"👋 ¡Hola, {name}!\n"
        f"Bienvenido/a a {PROJECT_NAME} 🌎\n"
        "━━━━━━━━━━━━━━━━━\n\n"
        "Aquí puedes completar tareas, acumular puntos y canjearlos por premios reales en nuestras empresas aliadas.\n\n"
        "📌 Comandos disponibles\n"
        "━━━━━━━━━━━━━━━━━\n"
        "📋 /tareas — Tareas activas hoy\n"
        "💰 /mis_puntos — Tu saldo actual\n"
        "🎁 /premios — Catálogo de premios\n"
        "🛒 /canjear — Canjear tus puntos\n"
        "🎟️ /mis_canjes — Tus canjes anteriores\n"
        "🗂️ /historial — Tus últimas tareas\n\n"
        "💬 También puedes escribirme cualquier pregunta y te respondo.\n\n"
        "📸 Para completar una tarea, envíame el screenshot como foto en este chat."
    )


# ─── /mis_puntos ─────────────────────────────────────────────────────────────

async def mis_puntos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _ensure_user(update)
    completions = db.get_user_completions(user["user_id"], limit=3)
    recent = ""
    if completions:
        recent = "\n\n📋 Últimas actividades\n━━━━━━━━━━━━━━━━━"
        for c in completions:
            emoji = "✅" if c["status"] == "approved" else ("⏳" if c["status"] == "pending" else "❌")
            pts = f"  +{c['points_awarded']} pts" if c["status"] == "approved" else ""
            recent += f"\n{emoji} {c['title']}{pts}"
    await update.message.reply_text(
        f"💰 Tus Puntos — {PROJECT_NAME}\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"👤 {user['full_name']}\n"
        f"⭐ Saldo: {user['points']} pts{recent}"
    )


# ─── /historial ──────────────────────────────────────────────────────────────

async def historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _ensure_user(update)
    completions = db.get_user_completions(user["user_id"], limit=10)
    if not completions:
        await update.message.reply_text("📭 No has completado ninguna tarea todavía.")
        return
    lines = [
        "📋 Tu Historial de Tareas",
        "━━━━━━━━━━━━━━━━━",
    ]
    for c in completions:
        emoji = {"approved": "✅", "pending": "⏳", "rejected": "❌"}.get(c["status"], "❓")
        pts = f" · +{c['points_awarded']} pts" if c["status"] == "approved" else ""
        date = c["submitted_at"][:10]
        lines.append(f"\n{emoji} {c['title']}{pts}\n   📅 {date}")
    await update.message.reply_text("\n".join(lines))


# ─── /premios ────────────────────────────────────────────────────────────────

async def ver_premios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _ensure_user(update)
    products = db.list_redeemable_products()
    if not products:
        await update.message.reply_text("📭 No hay premios disponibles por el momento.")
        return
    lines = [
        f"🎁 Catálogo de Premios — {PROJECT_NAME}",
        "━━━━━━━━━━━━━━━━━",
        f"💰 Tus puntos: {user['points']}",
        "━━━━━━━━━━━━━━━━━",
    ]
    for r in products:
        can = "✅" if user["points"] >= r["points_required"] else "🔒"
        lines.append(
            f"\n{can} {r['name']}\n"
            f"   💰 {r['points_required']} pts\n"
            f"   🏢 {r['provider']}"
        )
    lines.append("\n━━━━━━━━━━━━━━━━━")
    lines.append("🛒 Usa /canjear para redimir tus puntos")
    await update.message.reply_text("\n".join(lines))


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

    # Verificar stock disponible este mes
    if not db.product_has_stock(product_id):
        logger.info(f"[REDEEM] Sin stock product={product_id}")
        await update.message.reply_text(
            "🔒 Este premio se agotó por este mes\n"
            "━━━━━━━━━━━━━━━━━\n"
            "Vuelve el próximo mes o canjea otro premio.\n\n"
            "Usa /canjear para ver los disponibles."
        )
        return

    success = db.subtract_points(user_id, product["points_required"])
    logger.info(f"[REDEEM] subtract_points success={success}")
    if not success:
        await update.message.reply_text("❌ Error al procesar el canje. Intenta de nuevo.")
        return

    voucher_code = secrets.token_hex(4).upper()
    db.create_redemption(user_id, product_id, product["points_required"], voucher_code)
    stock_info = db.increment_product_redemption(product_id)
    updated_user = db.get_user(user_id)
    logger.info(f"[REDEEM] Redemption creada code={voucher_code} stock={stock_info}")

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
        "✅ ¡Canje Exitoso!\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"🎁 {product['name']}\n"
        f"🏢 {product['provider']}\n"
        f"💰 Puntos usados: {product['points_required']}\n"
        f"⭐ Nuevo saldo: {updated_user['points']} pts\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"🎟️ Código: {voucher_code}\n\n"
        "Presenta este código al momento de usar tu premio."
    )

    if voucher_path and os.path.exists(voucher_path):
        try:
            with open(voucher_path, "rb") as f:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=f,
                    caption=f"🎟️ Tu comprobante de canje\nCódigo: {voucher_code}"
                )
            logger.info(f"[REDEEM] Voucher enviado al usuario")
        except Exception as e:
            logger.exception(f"[REDEEM] Error enviando voucher photo: {e}")
    else:
        logger.warning(f"[REDEEM] Voucher path no existe: {voucher_path}")

    # Notificar al proveedor por Telegram
    try:
        await _notify_provider(context.bot, product, user, voucher_code, stock_info)
    except Exception as e:
        logger.exception(f"[REDEEM] Error notificando provider: {e}")


async def _notify_provider(bot, product, user, voucher_code, stock_info=None):
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

        if not row:
            return

        provider_chat_id = row["user_id"]

        # Notificación principal del canje
        await bot.send_message(
            chat_id=provider_chat_id,
            text=(
                "🔔 ¡Nuevo Canje en tu Empresa!\n"
                "━━━━━━━━━━━━━━━━━\n"
                f"🏢 {product['provider']}\n"
                f"👤 Cliente: {user['full_name']}\n"
                f"🎁 Producto: {product['name']}\n"
                f"💰 Puntos canjeados: {product['points_required']}\n"
                "━━━━━━━━━━━━━━━━━\n"
                f"🎟️ Código: {voucher_code}\n\n"
                "El cliente presentará este código para redimir su premio."
            )
        )

        # Alerta de stock al 80%
        if stock_info and stock_info.get("just_crossed_80"):
            try:
                await bot.send_message(
                    chat_id=provider_chat_id,
                    text=(
                        "⚠️ Alerta de Stock\n"
                        "━━━━━━━━━━━━━━━━━\n"
                        f"🎁 {product['name']}\n"
                        f"🏢 {product['provider']}\n\n"
                        f"📊 Cupos canjeados este mes: {stock_info['new_count']} de {stock_info['stock']}\n"
                        f"📈 {stock_info['percent']:.0f}% del stock mensual\n\n"
                        "Si quieres ampliar el cupo del mes, ajústalo en el panel admin."
                    )
                )
            except Exception as alert_err:
                logger.warning(f"No se pudo enviar alerta 80%: {alert_err}")
    except Exception as e:
        logger.warning(f"No se pudo notificar al proveedor: {e}")


# ─── /canjear ────────────────────────────────────────────────────────────────

async def canjear_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_USERNAME
    user = _ensure_user(update)
    rewards = [r for r in db.list_redeemable_products() if user["points"] >= r["points_required"]]

    if not rewards:
        await update.message.reply_text(
            "🔒 Necesitas más puntos para canjear\n"
            "━━━━━━━━━━━━━━━━━\n"
            f"💰 Tus puntos actuales: {user['points']}\n\n"
            "Completa más tareas para acumular puntos."
        )
        return

    args = context.args

    # /canjear <reward_id> → canjear directo
    if args and args[0].isdigit():
        await _process_redeem(update, context, args[0])
        return

    # /canjear <provider_id> → mostrar premios de esa empresa
    if args and args[0].startswith("ally_"):
        try:
            ally_id = int(args[0].replace("ally_", ""))
        except ValueError:
            await update.message.reply_text("❌ Empresa no válida.")
            return
        provider_rewards = [r for r in rewards if r.get("ally_id") == ally_id]
        if not provider_rewards:
            await update.message.reply_text("❌ No hay premios disponibles en esta empresa para tus puntos.")
            return
        await _show_provider_products(update, user, provider_rewards)
        return

    # /canjear <nombre_empresa> (legacy texto)
    if args and not args[0].isdigit():
        provider_name = " ".join(args)
        provider_rewards = [r for r in rewards if r["provider"].lower() == provider_name.lower()]
        if not provider_rewards:
            await update.message.reply_text("❌ No hay premios disponibles en esta empresa para tus puntos.")
            return
        await _show_provider_products(update, user, provider_rewards)
        return

    # Por defecto: mostrar lista de empresas con botones (callback_data)
    providers = {}
    for r in rewards:
        prov = r["provider"]
        ally_id = r.get("ally_id")
        if prov not in providers:
            providers[prov] = {"count": 0, "ally_id": ally_id}
        providers[prov]["count"] += 1

    keyboard = []
    for prov, info in providers.items():
        keyboard.append([InlineKeyboardButton(
            f"🏢 {prov} ({info['count']} premios)",
            callback_data=f"cnj_a_{info['ally_id']}"
        )])

    await update.message.reply_text(
        "🎁 Canjear Puntos\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"💰 Tus puntos: {user['points']}\n\n"
        "Selecciona la empresa donde quieres redimir:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _show_provider_products(update_or_query, user, provider_rewards):
    """Muestra los productos de una empresa con botones callback_data."""
    keyboard = []
    for r in provider_rewards:
        keyboard.append([InlineKeyboardButton(
            f"🎁 {r['name']} — {r['points_required']} pts",
            callback_data=f"cnj_p_{r['id']}"
        )])
    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver a empresas",
        callback_data="cnj_back"
    )])

    text = (
        f"🏢 {provider_rewards[0]['provider']}\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"💰 Tus puntos: {user['points']}\n\n"
        "Selecciona el premio que deseas:"
    )
    markup = InlineKeyboardMarkup(keyboard)

    if hasattr(update_or_query, "callback_query") and update_or_query.callback_query:
        await update_or_query.callback_query.edit_message_text(
            text, reply_markup=markup
        )
    elif hasattr(update_or_query, "message") and update_or_query.message:
        await update_or_query.message.reply_text(
            text, reply_markup=markup
        )
    else:
        # Es un Update con callback_query
        await update_or_query.callback_query.edit_message_text(
            text, reply_markup=markup
        )


async def canjear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja los callback_query del flujo de canje."""
    query = update.callback_query
    await query.answer()
    data = query.data
    logger.info(f"[CANJEAR_CB] data={data} user={query.from_user.id}")

    user_id = query.from_user.id
    db.upsert_user(user_id, query.from_user.username or "",
                   query.from_user.full_name or query.from_user.first_name or "")
    user = db.get_user(user_id)

    if data == "cnj_back":
        # Mostrar lista de empresas otra vez
        rewards = [r for r in db.list_redeemable_products() if user["points"] >= r["points_required"]]
        providers = {}
        for r in rewards:
            prov = r["provider"]
            ally_id = r.get("ally_id")
            if prov not in providers:
                providers[prov] = {"count": 0, "ally_id": ally_id}
            providers[prov]["count"] += 1
        keyboard = [[InlineKeyboardButton(
            f"🏢 {prov} ({info['count']} premios)",
            callback_data=f"cnj_a_{info['ally_id']}"
        )] for prov, info in providers.items()]
        await query.edit_message_text(
            "🎁 Canjear Puntos\n"
            "━━━━━━━━━━━━━━━━━\n"
            f"💰 Tus puntos: {user['points']}\n\n"
            "Selecciona la empresa donde quieres redimir:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("cnj_a_"):
        try:
            ally_id = int(data.replace("cnj_a_", ""))
        except ValueError:
            await query.edit_message_text("❌ Empresa no válida.")
            return
        rewards = [r for r in db.list_redeemable_products()
                   if user["points"] >= r["points_required"] and r.get("ally_id") == ally_id]
        if not rewards:
            await query.edit_message_text("❌ No hay premios disponibles en esta empresa para tus puntos.")
            return
        await _show_provider_products(update, user, rewards)
        return

    if data.startswith("cnj_p_"):
        product_id = data.replace("cnj_p_", "")
        # Confirmar canje en el mensaje y proceder
        await _process_redeem_callback(query, context, product_id)
        return


async def _process_redeem_callback(query, context, product_id_str):
    """Versión de _process_redeem para callback_query."""
    user_id = query.from_user.id
    logger.info(f"[REDEEM_CB] user={user_id} product={product_id_str}")

    if not product_id_str.isdigit():
        await query.edit_message_text("❌ Producto no válido.")
        return

    product_id = int(product_id_str)
    user = db.get_user(user_id)
    product = db.get_product(product_id)

    if not product or not product["is_active"] or product["points_required"] <= 0:
        await query.edit_message_text("❌ Ese producto no existe o no está disponible.")
        return
    if user["points"] < product["points_required"]:
        await query.edit_message_text(
            f"❌ No tienes suficientes puntos.\n"
            f"Necesitas: {product['points_required']} | Tienes: {user['points']}"
        )
        return

    if not db.product_has_stock(product_id):
        await query.edit_message_text(
            "🔒 Este premio se agotó por este mes\n"
            "━━━━━━━━━━━━━━━━━\n"
            "Vuelve el próximo mes o canjea otro premio.\n\n"
            "Usa /canjear para ver los disponibles."
        )
        return

    success = db.subtract_points(user_id, product["points_required"])
    if not success:
        await query.edit_message_text("❌ Error al procesar el canje. Intenta de nuevo.")
        return

    voucher_code = secrets.token_hex(4).upper()
    db.create_redemption(user_id, product_id, product["points_required"], voucher_code)
    stock_info = db.increment_product_redemption(product_id)
    updated_user = db.get_user(user_id)
    logger.info(f"[REDEEM_CB] Redemption code={voucher_code} stock={stock_info}")

    try:
        voucher_path = generate_voucher(
            user_name=user["full_name"],
            reward_name=product["name"],
            provider=product["provider"],
            points_used=product["points_required"],
            new_balance=updated_user["points"],
            voucher_code=voucher_code
        )
        logger.info(f"[REDEEM_CB] Voucher: {voucher_path}")
    except Exception as e:
        logger.exception(f"[REDEEM_CB] Error voucher: {e}")
        voucher_path = None

    await query.edit_message_text(
        "✅ ¡Canje Exitoso!\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"🎁 {product['name']}\n"
        f"🏢 {product['provider']}\n"
        f"💰 Puntos usados: {product['points_required']}\n"
        f"⭐ Nuevo saldo: {updated_user['points']} pts\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"🎟️ Código: {voucher_code}\n\n"
        "Presenta este código al momento de usar tu premio."
    )

    if voucher_path and os.path.exists(voucher_path):
        try:
            with open(voucher_path, "rb") as f:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=f,
                    caption=f"🎟️ Tu comprobante de canje\nCódigo: {voucher_code}"
                )
            logger.info(f"[REDEEM_CB] Voucher enviado")
        except Exception as e:
            logger.exception(f"[REDEEM_CB] Error enviando voucher: {e}")

    try:
        await _notify_provider(context.bot, product, user, voucher_code, stock_info)
    except Exception as e:
        logger.exception(f"[REDEEM_CB] Error notificando provider: {e}")


# ─── /mis_canjes ─────────────────────────────────────────────────────────────

async def mis_canjes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _ensure_user(update)
    redemptions = db.get_user_redemptions(user["user_id"])
    if not redemptions:
        await update.message.reply_text("📭 No has realizado ningún canje todavía.")
        return
    lines = [
        "🎟️ Tus Canjes",
        "━━━━━━━━━━━━━━━━━",
    ]
    for r in redemptions:
        status_emoji = "✅" if r["status"] == "active" else "🔴"
        lines.append(
            f"\n{status_emoji} {r['name']}\n"
            f"   🏢 {r['provider']}\n"
            f"   💰 {r['points_used']} pts\n"
            f"   🎟️ Código: {r['voucher_code']}\n"
            f"   📅 {r['redeemed_at'][:10]}"
        )
    await update.message.reply_text("\n".join(lines))


# ─── Recibir screenshot ───────────────────────────────────────────────────────

async def receive_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """El usuario envía una foto como comprobante. La IA detecta a cuál tarea del día corresponde."""
    from validator import detect_and_validate

    user = _ensure_user(update)

    # Verificar que haya tareas activas hoy
    active_today = db.list_active_tasks_today()
    if not active_today:
        await update.message.reply_text(
            "⚠️ No hay tareas activas hoy.\n"
            "Las tareas solo se pueden completar el mismo día en que se publican.\n\n"
            "Mantente atento al canal para las próximas tareas."
        )
        return

    # Descargar y guardar el screenshot
    photo = update.message.photo[-1]  # mayor resolución
    file = await photo.get_file()
    screenshot_path = os.path.join(
        SCREENSHOTS_DIR,
        f"{user['user_id']}_{int(datetime.now().timestamp())}.jpg"
    )
    await file.download_to_drive(screenshot_path)

    await update.message.reply_text(
        "📸 Comprobante recibido. Validando con IA... ⏳"
    )

    # Validar con IA — detecta automáticamente a qué tarea corresponde
    result = await detect_and_validate(context.bot, user["user_id"], screenshot_path)

    if not result["ok"]:
        err = result.get("error", "")
        if err == "no_active_tasks":
            await update.message.reply_text(
                "⚠️ No hay tareas activas hoy. Espera la próxima publicación."
            )
        elif err == "all_completed":
            await update.message.reply_text(
                "✅ Ya completaste todas las tareas de hoy. ¡Espera las de mañana!"
            )
        elif err == "no_match":
            reason = result.get("reason", "")
            await update.message.reply_text(
                f"❌ No pude identificar a qué tarea corresponde este screenshot.\n\n"
                f"{reason}\n\n"
                "Asegúrate de que el screenshot muestre claramente la acción "
                "realizada en la página/empresa indicada en alguna de las tareas activas hoy."
            )
        elif err == "duplicate":
            await update.message.reply_text(
                "⚠️ Ya enviaste un comprobante para esa tarea."
            )
        elif err == "rejected":
            # El mensaje ya lo envió detect_and_validate
            pass
        else:
            await update.message.reply_text(
                "⏳ Tu comprobante está en revisión. Te notificaremos pronto."
            )


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
            f"👋 ¡Bienvenido/a, {name}!\n"
            "━━━━━━━━━━━━━━━━━\n"
            f"Has llegado a {PROJECT_NAME} 🌎\n"
            "La red de turismo colaborativo.\n\n"
            "🎮 ¿Cómo funciona?\n"
            "━━━━━━━━━━━━━━━━━\n"
            "1️⃣ Publicamos tareas en este grupo\n"
            "    (dar like, comentar, compartir)\n"
            "2️⃣ Completas la tarea\n"
            "3️⃣ Envías el screenshot al bot\n"
            "4️⃣ La IA valida y ganas puntos\n"
            "5️⃣ Canjeas tus puntos por premios reales\n\n"
            "💰 Tabla de puntos\n"
            "━━━━━━━━━━━━━━━━━\n"
            "👍 Me gusta / Compartir → 10 pts\n"
            "💬 Comentar → 15 pts\n"
            "🎁 Desde 20 pts puedes canjear\n\n"
            f"📲 Escríbele al bot @{BOT_USERNAME} en privado.\n"
            "Usa /start para ver todos los comandos."
        )
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

        lines = [
            f"📌 Tareas activas — {filtered[0]['business_name']}",
            "━━━━━━━━━━━━━━━━━"
        ]
        for t in filtered:
            url_line = f"\n   🔗 {t['target_url']}" if t.get("target_url") else ""
            lines.append(
                f"\n📌 {t['title']}\n"
                f"   {t['description']}\n"
                f"   📋 {t['instructions']}{url_line}\n"
                f"   💰 {t['points_value']} puntos"
            )
        lines.append("\n━━━━━━━━━━━━━━━━━")
        lines.append("📸 Envía el screenshot a este chat para validar")
        await update.message.reply_text("\n".join(lines))
        return

    # Sin argumento: agrupar por empresa
    by_provider = {}
    for t in sent_tasks:
        by_provider.setdefault(t["business_name"], []).append(t)

    lines = [
        "📌 Tareas Activas por Empresa",
        "━━━━━━━━━━━━━━━━━"
    ]
    for provider, tasks in by_provider.items():
        lines.append(f"\n🏢 {provider} ({len(tasks)} tareas)\n   👉 /tareas {provider}")
    lines.append("\n💡 Toca el comando para ver las tareas de esa empresa")
    await update.message.reply_text("\n".join(lines))


# ─── Registro ────────────────────────────────────────────────────────────────

async def chat_with_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe mensajes de texto privados y responde con el agente IA."""
    from chat_agent import chat_response

    # No interferir si el admin está esperando ingresar un código de voucher
    if context.user_data.get("waiting_code"):
        return

    user = _ensure_user(update)
    msg_text = update.message.text or ""

    # Mostrar "escribiendo..." mientras procesa
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing"
        )
    except Exception:
        pass

    response = await chat_response(user["user_id"], msg_text)

    # Sin Markdown para evitar errores de parseo
    await update.message.reply_text(response)


def register(app):
    from telegram.ext import filters as f

    # Canjear: /canjear o /canjear <id> + callback_query handler
    app.add_handler(CommandHandler("canjear", canjear_start))
    app.add_handler(CallbackQueryHandler(canjear_callback, pattern=r"^cnj_"))

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

    # Agente conversacional: responde mensajes de texto en chat privado (no comandos)
    app.add_handler(MessageHandler(
        f.TEXT & ~f.COMMAND & f.ChatType.PRIVATE,
        chat_with_agent
    ))
