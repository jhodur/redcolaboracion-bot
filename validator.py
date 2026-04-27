"""
Validador de screenshots usando Claude Vision (Anthropic).
Analiza la imagen y determina si el usuario completó la tarea.
"""

import base64
import logging
import os
import anthropic

import database as db
from config import ANTHROPIC_API_KEY, PROJECT_NAME

logger = logging.getLogger(__name__)

_client = None


def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _build_prompt(task: dict) -> str:
    url_info = f"\nURL objetivo: {task['target_url']}" if task.get("target_url") else ""
    return f"""Eres el validador automático de tareas del sistema de gamificación de {PROJECT_NAME}.

Se le pidió al usuario realizar la siguiente tarea:

TAREA: {task['title']}
DESCRIPCIÓN: {task['description']}
INSTRUCCIONES: {task['instructions']}{url_info}

El usuario ha enviado un screenshot como comprobante.

Analiza la imagen y determina:
1. ¿El screenshot muestra evidencia de haber completado la tarea descrita?
2. ¿Se puede ver claramente que se realizó la acción requerida (like, comentario, compartir, etc.)?
3. ¿La imagen parece auténtica y no editada artificialmente?

Responde ÚNICAMENTE en este formato JSON (sin texto adicional):
{{
  "approved": true o false,
  "confidence": número del 0 al 100,
  "reason": "explicación breve en español de por qué se aprueba o rechaza"
}}

Sé generoso con la aprobación si hay evidencia razonable de la acción.
Solo rechaza si claramente NO muestra la tarea o la imagen está en blanco/irrelevante."""


async def validate_and_award(bot, completion: dict):
    """Valida un screenshot y otorga o rechaza los puntos."""
    screenshot_path = completion["screenshot_path"]

    if not os.path.exists(screenshot_path):
        db.update_completion(completion["id"], "rejected", 0, "Archivo no encontrado")
        return

    try:
        with open(screenshot_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        task = db.get_task(completion["task_id"])
        prompt = _build_prompt(task)

        client = get_client()
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data,
                        }
                    },
                    {"type": "text", "text": prompt}
                ]
            }]
        )

        raw = response.content[0].text.strip()

        # Parsear JSON
        import json
        # Limpiar posibles bloques de código
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())

        approved = result.get("approved", False)
        confidence = result.get("confidence", 0)
        reason = result.get("reason", "")

        if approved and confidence >= 50:
            status = "approved"
            points = task["points_value"]
            db.update_completion(completion["id"], status, points, reason)
            db.add_points(completion["user_id"], points)
            updated_user = db.get_user(completion["user_id"])

            # Notificar al usuario (sin Markdown para evitar errores de parseo)
            try:
                await bot.send_message(
                    chat_id=completion["user_id"],
                    text=(
                        f"✅ ¡Tarea validada!\n\n"
                        f"📌 {task['title']}\n"
                        f"💰 +{points} puntos ganados\n"
                        f"⭐ Tu saldo: {updated_user['points']} pts\n\n"
                        f"{reason}\n\n"
                        "🎁 ¿Quieres canjear tus puntos?\n"
                        "Escribe /canjear para ver los premios disponibles"
                    )
                )
            except Exception as notify_err:
                logger.warning(f"No se pudo notificar aprobacion al usuario: {notify_err}")
        else:
            status = "rejected"
            db.update_completion(completion["id"], status, 0, reason)
            try:
                await bot.send_message(
                    chat_id=completion["user_id"],
                    text=(
                        f"❌ Comprobante no válido\n\n"
                        f"📌 {task['title']}\n\n"
                        f"Motivo: {reason}\n\n"
                        "Por favor intenta de nuevo con un screenshot más claro "
                        "que muestre la acción realizada."
                    )
                )
            except Exception as notify_err:
                logger.warning(f"No se pudo notificar rechazo al usuario: {notify_err}")

    except Exception as e:
        # Si falla la IA, aprobar manualmente o marcar para revisión
        db.update_completion(completion["id"], "pending", 0, f"Error de validación: {str(e)}")
        try:
            await bot.send_message(
                chat_id=completion["user_id"],
                text=(
                    "⏳ Tu comprobante está siendo revisado manualmente.\n"
                    "Te notificaremos pronto."
                )
            )
        except Exception:
            pass


async def validate_screenshot(bot, pending: dict):
    """Wrapper para procesar un pendiente desde el panel admin."""
    completion = db.get_completion(pending["id"])
    if completion:
        await validate_and_award(bot, completion)
