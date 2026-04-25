"""
Auto-scheduler de tareas.
Cada día genera automáticamente 4 slots de tareas (7am, 12pm, 3pm, 7pm)
rotando entre empresas según su plan (tasks_per_week).
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from config import DB_PATH

logger = logging.getLogger(__name__)

SLOT_HOURS = [7, 12, 15, 19]  # 7am, 12pm, 3pm, 7pm
SLOTS_PER_DAY = len(SLOT_HOURS)


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _week_start(dt):
    """Lunes 00:00 de la semana de dt."""
    monday = dt - timedelta(days=dt.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def get_ally_task_count_this_week(ally_id, week_start):
    """Cuenta cuántas tareas auto-generadas tiene programadas/enviadas esta empresa esta semana."""
    conn = _get_conn()
    week_end = week_start + timedelta(days=7)
    count = conn.execute("""
        SELECT COUNT(*) FROM scheduled_tasks st
        JOIN tasks t ON t.id = st.task_id
        WHERE t.ally_id = ?
          AND st.auto_generated = 1
          AND st.send_at >= ?
          AND st.send_at < ?
    """, (ally_id, week_start.strftime("%Y-%m-%d %H:%M:%S"),
          week_end.strftime("%Y-%m-%d %H:%M:%S"))).fetchone()[0]
    conn.close()
    return count


def get_next_task_for_ally(ally_id):
    """Obtiene la siguiente tarea activa de una empresa (rotación simple)."""
    conn = _get_conn()
    # Tareas activas de la empresa, ordenadas por menor uso reciente
    row = conn.execute("""
        SELECT t.*,
               (SELECT MAX(st.send_at) FROM scheduled_tasks st WHERE st.task_id = t.id) as last_sent
        FROM tasks t
        WHERE t.ally_id = ? AND t.is_active = 1
        ORDER BY last_sent ASC NULLS FIRST, t.id ASC
        LIMIT 1
    """, (ally_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def generate_daily_schedule(target_date=None):
    """
    Genera los 4 slots del día rotando entre empresas aprobadas.
    Respeta el límite de tasks_per_week por empresa.
    Solo crea slots que aún no existan.
    Retorna lista de scheduled_task IDs creados.
    """
    if target_date is None:
        target_date = datetime.now().date()

    week_start = _week_start(datetime.combine(target_date, datetime.min.time()))

    conn = _get_conn()
    # Empresas aprobadas con al menos una tarea activa
    allies = conn.execute("""
        SELECT a.id, a.business_name, a.tasks_per_week
        FROM allies a
        WHERE a.status = 'approved'
          AND EXISTS (SELECT 1 FROM tasks t WHERE t.ally_id = a.id AND t.is_active = 1)
        ORDER BY a.id
    """).fetchall()
    allies = [dict(a) for a in allies]
    conn.close()

    if not allies:
        logger.info("Auto-scheduler: no hay empresas aprobadas con tareas activas.")
        return []

    created_ids = []

    for slot_idx, hour in enumerate(SLOT_HOURS):
        slot_dt = datetime.combine(target_date, datetime.min.time()).replace(hour=hour)

        # Si ya pasó la hora del slot, saltar (no generar tareas pasadas)
        if slot_dt < datetime.now() - timedelta(minutes=5):
            continue

        # Verificar si ya existe un slot auto-generado a esta hora
        conn = _get_conn()
        existing = conn.execute("""
            SELECT id FROM scheduled_tasks
            WHERE auto_generated = 1 AND send_at = ?
        """, (slot_dt.strftime("%Y-%m-%d %H:%M:%S"),)).fetchone()
        conn.close()
        if existing:
            continue

        # Elegir empresa: la que tenga menos tareas esta semana y no haya excedido su plan
        candidates = []
        for ally in allies:
            count = get_ally_task_count_this_week(ally["id"], week_start)
            if count < ally["tasks_per_week"]:
                candidates.append((count, ally))
        if not candidates:
            logger.info(f"Slot {slot_dt}: todas las empresas alcanzaron su límite semanal.")
            continue

        # Empresa con menor count
        candidates.sort(key=lambda x: (x[0], x[1]["id"]))
        chosen = candidates[0][1]

        # Obtener tarea de esa empresa
        task = get_next_task_for_ally(chosen["id"])
        if not task:
            logger.warning(f"Empresa {chosen['business_name']} sin tareas activas.")
            continue

        # Crear el scheduled_task
        conn = _get_conn()
        cur = conn.execute("""
            INSERT INTO scheduled_tasks (task_id, send_at, auto_generated, slot_time)
            VALUES (?, ?, 1, ?)
        """, (task["id"], slot_dt.strftime("%Y-%m-%d %H:%M:%S"),
              f"{hour:02d}:00"))
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        created_ids.append(new_id)
        logger.info(f"Auto-scheduled: {chosen['business_name']} -> '{task['title']}' @ {slot_dt}")

    return created_ids


async def auto_schedule_job(context):
    """Job que corre periódicamente (cada hora) para generar slots del día/mañana."""
    try:
        today_ids = generate_daily_schedule(datetime.now().date())
        # También planificar mañana después de las 6pm
        if datetime.now().hour >= 18:
            tomorrow_ids = generate_daily_schedule((datetime.now() + timedelta(days=1)).date())
        else:
            tomorrow_ids = []
        if today_ids or tomorrow_ids:
            logger.info(f"Auto-scheduler creó {len(today_ids)} slots hoy y {len(tomorrow_ids)} mañana.")
    except Exception as e:
        logger.error(f"Error en auto_schedule_job: {e}", exc_info=True)


def setup_auto_scheduler(app):
    """Registra el job de auto-generación cada hora."""
    app.job_queue.run_repeating(
        auto_schedule_job,
        interval=3600,  # cada hora
        first=30        # primera ejecución a los 30s del arranque
    )
    logger.info("Auto-scheduler iniciado (revisa cada hora)")
