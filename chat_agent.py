"""
Agente conversacional con Claude para responder consultas de los usuarios
sobre puntos, premios, tareas, canjes y dinámica de Red Colaboración.
"""

import logging
import sqlite3
from datetime import datetime
import anthropic

import database as db
from config import ANTHROPIC_API_KEY, PROJECT_NAME, DB_PATH

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _get_user_context(user_id: int) -> dict:
    """Reúne todo el contexto del usuario para el agente."""
    user = db.get_user(user_id)
    if not user:
        return {}

    # Tareas activas del día
    active_tasks = db.list_active_tasks_today()
    tasks_info = []
    for t in active_tasks:
        completed = db.has_completed_task(user_id, t["scheduled_id"])
        tasks_info.append({
            "id": t["id"],
            "title": t["title"],
            "description": t["description"],
            "instructions": t["instructions"],
            "url": t.get("target_url"),
            "points": t["points_value"],
            "business": t["business_name"],
            "user_already_completed": completed,
        })

    # Productos canjeables
    products = db.list_redeemable_products()
    products_info = [{
        "id": p["id"],
        "name": p["name"],
        "points_required": p["points_required"],
        "provider": p["provider"],
        "user_can_afford": user["points"] >= p["points_required"],
    } for p in products]

    # Últimos canjes del usuario
    redemptions = db.get_user_redemptions(user_id)[:5]
    red_info = [{
        "product": r["name"],
        "provider": r["provider"],
        "points": r["points_used"],
        "code": r["voucher_code"],
        "status": r["status"],
        "date": r["redeemed_at"][:10] if r.get("redeemed_at") else "",
    } for r in redemptions]

    # Últimas tareas del usuario
    completions = db.get_user_completions(user_id, limit=5)
    comp_info = [{
        "title": c["title"],
        "status": c["status"],
        "points_awarded": c["points_awarded"],
        "date": c["submitted_at"][:10] if c.get("submitted_at") else "",
    } for c in completions]

    return {
        "user": {
            "name": user["full_name"],
            "username": user["username"],
            "points": user["points"],
        },
        "active_tasks_today": tasks_info,
        "redeemable_products": products_info,
        "recent_redemptions": red_info,
        "recent_completions": comp_info,
    }


def _build_system_prompt(ctx: dict) -> str:
    """Construye el system prompt con todo el contexto del usuario."""
    user = ctx.get("user", {})
    tasks = ctx.get("active_tasks_today", [])
    products = ctx.get("redeemable_products", [])
    redemptions = ctx.get("recent_redemptions", [])
    completions = ctx.get("recent_completions", [])

    today = datetime.now().strftime("%d/%m/%Y")

    prompt = f"""Eres el asistente conversacional del bot de Telegram de **{PROJECT_NAME}**, una red colaborativa de turismo donde los usuarios completan tareas en redes sociales (likes, comentarios, compartir) para ganar puntos canjeables por premios reales en empresas aliadas.

Tu rol es responder de forma amable, breve y útil. Habla en español colombiano natural.

## CONTEXTO DEL USUARIO ACTUAL
- **Nombre:** {user.get('name', 'Usuario')}
- **Telegram:** @{user.get('username', '')}
- **Puntos disponibles:** {user.get('points', 0)} pts
- **Fecha actual:** {today}

## CÓMO FUNCIONA
- Cada día se publican hasta 4 tareas en el canal (likes, comentarios, compartir, seguir, etc.)
- El usuario ve la tarea, la realiza, y envía el screenshot como prueba al bot en privado
- La IA valida el screenshot y otorga los puntos automáticamente
- **Importante:** las tareas SOLO se pueden completar el mismo día en que se publican. Las de días anteriores YA NO sirven.
- Los puntos se canjean por premios (productos, descuentos, bebidas, etc.) en empresas aliadas
- Cada premio tiene un costo en puntos. Al canjear, el bot envía un voucher con código.

## TAREAS ACTIVAS HOY ({today})
"""

    if tasks:
        for t in tasks:
            done = "✅ YA LA COMPLETASTE" if t["user_already_completed"] else "⏳ pendiente"
            prompt += f"- **{t['title']}** | Empresa: {t['business']} | {t['points']} pts | {done}\n"
            prompt += f"   Descripción: {t['description']}\n"
            if t.get("url"):
                prompt += f"   URL: {t['url']}\n"
    else:
        prompt += "- (Hoy no hay tareas activas. El usuario debe esperar las próximas publicaciones del canal.)\n"

    prompt += "\n## PREMIOS DISPONIBLES PARA CANJEAR\n"
    if products:
        for p in products:
            afford = "✅ puede canjear" if p["user_can_afford"] else "🔒 le faltan puntos"
            prompt += f"- {p['name']} | {p['provider']} | {p['points_required']} pts | {afford}\n"
    else:
        prompt += "- (Aún no hay productos canjeables registrados.)\n"

    if redemptions:
        prompt += "\n## SUS CANJES RECIENTES\n"
        for r in redemptions:
            prompt += f"- {r['product']} ({r['provider']}) | {r['points']} pts | Código: {r['code']} | {r['status']} | {r['date']}\n"

    if completions:
        prompt += "\n## SUS ÚLTIMAS TAREAS\n"
        for c in completions:
            emoji = {"approved": "✅", "pending": "⏳", "rejected": "❌"}.get(c["status"], "❓")
            prompt += f"- {emoji} {c['title']} | {c['status']} | +{c['points_awarded']} pts | {c['date']}\n"

    prompt += """

## INSTRUCCIONES DE RESPUESTA
- Sé breve, amable y conversacional. Sin Markdown excesivo.
- Si te preguntan por puntos, dales el saldo y sugiere qué pueden hacer (canjear, completar tarea).
- Si te preguntan por tareas activas, listalas con el nombre y los puntos.
- Si te preguntan por premios, listalos con el costo y empresa.
- Si te piden canjear, sugiéreles usar el comando /canjear (tienen botones interactivos).
- Si quieren ver tareas, sugiere /tareas o que vean directamente el canal.
- Si el usuario pide ayuda, lista los comandos disponibles: /start, /tareas, /mis_puntos, /premios, /canjear, /mis_canjes, /historial
- Si pregunta cómo enviar evidencia, dile que envíe la foto/screenshot a este chat privado y la IA detectará automáticamente a qué tarea corresponde.
- NUNCA inventes información. Si no sabes algo, dilo o sugiere preguntar al admin.
- Mantén las respuestas cortas (máx 4-5 líneas para preguntas simples, máximo un párrafo).
- Usa emojis con moderación (1-2 por mensaje máximo).
"""
    return prompt


async def chat_response(user_id: int, message: str) -> str:
    """Genera una respuesta conversacional para el usuario usando Claude."""
    try:
        ctx = _get_user_context(user_id)
        if not ctx:
            return "Hola, escribe /start para comenzar."

        system_prompt = _build_system_prompt(ctx)
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=system_prompt,
            messages=[
                {"role": "user", "content": message}
            ]
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.exception(f"Error en chat_response: {e}")
        return ("Lo siento, tuve un error procesando tu mensaje. "
                "Puedes intentar /start para ver los comandos disponibles.")
