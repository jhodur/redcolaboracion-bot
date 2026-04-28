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
                        "✅ ¡Tarea Validada!\n"
                        "━━━━━━━━━━━━━━━━━\n"
                        f"📌 {task['title']}\n"
                        f"💰 +{points} puntos ganados\n"
                        f"⭐ Tu saldo: {updated_user['points']} pts\n"
                        "━━━━━━━━━━━━━━━━━\n"
                        f"💬 {reason}\n\n"
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
                        "❌ Comprobante No Válido\n"
                        "━━━━━━━━━━━━━━━━━\n"
                        f"📌 {task['title']}\n\n"
                        f"💬 Motivo: {reason}\n\n"
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


async def detect_and_validate(bot, user_id: int, screenshot_path: str):
    """
    Detecta automáticamente a qué tarea pendiente del usuario corresponde el screenshot.
    Considera todas las tareas activas que el usuario aún no haya completado.
    Si detecta y valida, registra la completion y otorga puntos.
    Retorna dict con resultado.
    """
    if not os.path.exists(screenshot_path):
        return {"ok": False, "error": "Archivo no encontrado"}

    # Tareas activas pendientes para este usuario (las que aún no completó)
    available = db.list_pending_tasks_for_user(user_id)
    if not available:
        # Verificar si es porque ya las completó todas o porque no hay activas
        all_active = db.list_active_tasks()
        if not all_active:
            return {"ok": False, "error": "no_active_tasks"}
        return {"ok": False, "error": "all_completed"}

    try:
        with open(screenshot_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        # Construir lista enumerada de tareas
        tasks_text_lines = []
        for i, t in enumerate(available, 1):
            url_info = f" | URL: {t['target_url']}" if t.get("target_url") else ""
            tasks_text_lines.append(
                f"{i}. ID={t['id']} | EMPRESA: {t['business_name']} | "
                f"TAREA: {t['title']} | "
                f"DESCRIPCIÓN: {t['description']} | "
                f"INSTRUCCIONES: {t['instructions']}{url_info}"
            )
        tasks_text = "\n".join(tasks_text_lines)

        prompt = f"""Eres el validador automático de tareas del sistema de gamificación de {PROJECT_NAME}.

El usuario envió un screenshot como evidencia. Tu trabajo es:
1. Determinar a CUÁL de las siguientes tareas activas corresponde el screenshot
2. Validar si la evidencia es válida para esa tarea

TAREAS ACTIVAS DEL DÍA:
{tasks_text}

Analiza la imagen y determina:
- ¿A cuál tarea (por su ID) corresponde el screenshot?
- ¿La evidencia es válida para esa tarea?
- ¿La imagen es auténtica?

Si el screenshot NO corresponde a ninguna de las tareas listadas, responde matched_task_id: null.

Responde ÚNICAMENTE en este formato JSON (sin texto adicional):
{{
  "matched_task_id": ID de la tarea o null si ninguna coincide,
  "approved": true si la evidencia es válida para esa tarea, false si no,
  "confidence": número del 0 al 100,
  "reason": "explicación breve en español"
}}

Sé generoso con la aprobación si hay evidencia razonable.
Si el screenshot muestra una acción de Facebook/Instagram pero no corresponde a la URL/empresa de las tareas listadas, marca matched_task_id como null."""

        client = get_client()
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=400,
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
        import json
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())

        matched_task_id = result.get("matched_task_id")
        approved = result.get("approved", False)
        confidence = result.get("confidence", 0)
        reason = result.get("reason", "")

        # Si no detectó tarea
        if not matched_task_id:
            return {"ok": False, "error": "no_match", "reason": reason}

        # Buscar la tarea detectada en la lista de disponibles
        matched = next((t for t in available if t["id"] == matched_task_id), None)
        if not matched:
            return {"ok": False, "error": "invalid_match", "reason": "Tarea detectada no está disponible"}

        # Crear la completion para esa tarea específica
        completion_id = db.submit_completion(
            user_id=user_id,
            task_id=matched["id"],
            scheduled_id=matched["scheduled_id"],
            screenshot_path=screenshot_path
        )

        if completion_id is None:
            return {"ok": False, "error": "duplicate"}

        if approved and confidence >= 50:
            points = matched["points_value"]
            db.update_completion(completion_id, "approved", points, reason)
            db.add_points(user_id, points)
            updated_user = db.get_user(user_id)

            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=(
                        "✅ ¡Tarea Validada!\n"
                        "━━━━━━━━━━━━━━━━━\n"
                        f"🏢 {matched['business_name']}\n"
                        f"📌 {matched['title']}\n"
                        f"💰 +{points} puntos ganados\n"
                        f"⭐ Tu saldo: {updated_user['points']} pts\n"
                        "━━━━━━━━━━━━━━━━━\n"
                        f"💬 {reason}\n\n"
                        "🎁 ¿Quieres canjear tus puntos?\n"
                        "Escribe /canjear para ver los premios disponibles"
                    )
                )
            except Exception as notify_err:
                logger.warning(f"No se pudo notificar al usuario: {notify_err}")

            return {"ok": True, "task": matched, "points": points}
        else:
            db.update_completion(completion_id, "rejected", 0, reason)
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=(
                        "❌ Comprobante No Válido\n"
                        "━━━━━━━━━━━━━━━━━\n"
                        f"🏢 {matched['business_name']}\n"
                        f"📌 {matched['title']}\n\n"
                        f"💬 Motivo: {reason}\n\n"
                        "Por favor intenta de nuevo con un screenshot más claro."
                    )
                )
            except Exception:
                pass
            return {"ok": False, "error": "rejected", "reason": reason}

    except Exception as e:
        logger.exception(f"Error en detect_and_validate: {e}")
        return {"ok": False, "error": "exception", "reason": str(e)}
