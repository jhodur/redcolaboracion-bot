"""
Capa de acceso a base de datos SQLite.
Todas las operaciones son síncronas usando sqlite3 estándar.
"""

import sqlite3
import json
from datetime import datetime
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            full_name   TEXT,
            points      INTEGER DEFAULT 0,
            joined_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            title           TEXT NOT NULL,
            description     TEXT NOT NULL,
            instructions    TEXT NOT NULL,
            target_url      TEXT,
            points_value    INTEGER DEFAULT 10,
            ally_id         INTEGER,
            created_by      INTEGER,
            created_at      TEXT DEFAULT (datetime('now')),
            is_active       INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id         INTEGER REFERENCES tasks(id),
            send_at         TEXT NOT NULL,
            sent            INTEGER DEFAULT 0,
            message_id      INTEGER,
            auto_generated  INTEGER DEFAULT 0,
            slot_time       TEXT
        );

        CREATE TABLE IF NOT EXISTS task_completions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER REFERENCES users(user_id),
            task_id         INTEGER REFERENCES tasks(id),
            scheduled_id    INTEGER REFERENCES scheduled_tasks(id),
            screenshot_path TEXT,
            status          TEXT DEFAULT 'pending',
            points_awarded  INTEGER DEFAULT 0,
            ai_response     TEXT,
            submitted_at    TEXT DEFAULT (datetime('now')),
            reviewed_at     TEXT
        );

        CREATE TABLE IF NOT EXISTS allies (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name   TEXT NOT NULL,
            owner_name      TEXT,
            phone           TEXT,
            email           TEXT,
            location        TEXT,
            city            TEXT,
            description     TEXT,
            photo_path      TEXT,
            instagram       TEXT,
            facebook        TEXT,
            website         TEXT,
            telegram_user   TEXT,
            tasks_per_week  INTEGER DEFAULT 7,
            status          TEXT DEFAULT 'pending',
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS ally_goals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ally_id     INTEGER REFERENCES allies(id),
            goal_type   TEXT NOT NULL,
            target      INTEGER DEFAULT 0,
            current     INTEGER DEFAULT 0,
            period      TEXT DEFAULT 'monthly',
            notes       TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS ally_products (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ally_id         INTEGER REFERENCES allies(id),
            name            TEXT NOT NULL,
            description     TEXT,
            price           TEXT,
            photo_path      TEXT,
            points_required INTEGER DEFAULT 0,
            is_active       INTEGER DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rewards (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            description     TEXT NOT NULL,
            points_required INTEGER NOT NULL,
            provider        TEXT,
            is_active       INTEGER DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS redemptions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER,
            reward_id       INTEGER,
            points_used     INTEGER NOT NULL,
            voucher_code    TEXT UNIQUE,
            status          TEXT DEFAULT 'active',
            redeemed_at     TEXT DEFAULT (datetime('now')),
            used_at         TEXT
        );
        """)


# ─── Users ───────────────────────────────────────────────────────────────────

def upsert_user(user_id: int, username: str, full_name: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username  = excluded.username,
                full_name = excluded.full_name
        """, (user_id, username, full_name))


def get_user(user_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def add_points(user_id: int, points: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET points = points + ? WHERE user_id = ?",
            (points, user_id)
        )


def subtract_points(user_id: int, points: int) -> bool:
    with get_conn() as conn:
        user = conn.execute("SELECT points FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user or user["points"] < points:
            return False
        conn.execute(
            "UPDATE users SET points = points - ? WHERE user_id = ?",
            (points, user_id)
        )
        return True


def get_leaderboard(limit: int = 10):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT user_id, full_name, username, points
            FROM users ORDER BY points DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


# ─── Tasks ───────────────────────────────────────────────────────────────────

def create_task(title, description, instructions, target_url, points_value, created_by, ally_id=None):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO tasks (title, description, instructions, target_url, points_value, ally_id, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (title, description, instructions, target_url, points_value, ally_id, created_by))
        return cur.lastrowid


def get_task(task_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def list_tasks(active_only: bool = True):
    with get_conn() as conn:
        q = "SELECT * FROM tasks"
        if active_only:
            q += " WHERE is_active = 1"
        q += " ORDER BY created_at DESC"
        return [dict(r) for r in conn.execute(q).fetchall()]


def deactivate_task(task_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET is_active = 0 WHERE id = ?", (task_id,))


# ─── Scheduled Tasks ─────────────────────────────────────────────────────────

def schedule_task(task_id: int, send_at: str):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO scheduled_tasks (task_id, send_at) VALUES (?, ?)",
            (task_id, send_at)
        )
        return cur.lastrowid


def get_pending_scheduled_tasks():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT st.*, t.title, t.description, t.instructions, t.target_url, t.points_value
            FROM scheduled_tasks st
            JOIN tasks t ON t.id = st.task_id
            WHERE st.sent = 0 AND st.send_at <= datetime('now')
              AND t.is_active = 1
            ORDER BY st.send_at ASC
        """).fetchall()
        return [dict(r) for r in rows]


def mark_scheduled_sent(scheduled_id: int, message_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE scheduled_tasks SET sent = 1, message_id = ? WHERE id = ?",
            (message_id, scheduled_id)
        )


def get_scheduled_task(scheduled_id: int):
    with get_conn() as conn:
        row = conn.execute("""
            SELECT st.*, t.title, t.description, t.instructions, t.target_url, t.points_value
            FROM scheduled_tasks st
            JOIN tasks t ON t.id = st.task_id
            WHERE st.id = ?
        """, (scheduled_id,)).fetchone()
        return dict(row) if row else None


def list_upcoming_scheduled():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT st.id, st.send_at, st.sent, t.title, t.points_value
            FROM scheduled_tasks st
            JOIN tasks t ON t.id = st.task_id
            ORDER BY st.send_at DESC LIMIT 20
        """).fetchall()
        return [dict(r) for r in rows]


# ─── Task Completions ────────────────────────────────────────────────────────

def submit_completion(user_id: int, task_id: int, scheduled_id: int, screenshot_path: str):
    with get_conn() as conn:
        existing = conn.execute("""
            SELECT id FROM task_completions
            WHERE user_id = ? AND scheduled_id = ? AND status != 'rejected'
        """, (user_id, scheduled_id)).fetchone()
        if existing:
            return None  # ya enviado
        cur = conn.execute("""
            INSERT INTO task_completions (user_id, task_id, scheduled_id, screenshot_path)
            VALUES (?, ?, ?, ?)
        """, (user_id, task_id, scheduled_id, screenshot_path))
        return cur.lastrowid


def update_completion(completion_id: int, status: str, points: int, ai_response: str):
    with get_conn() as conn:
        conn.execute("""
            UPDATE task_completions
            SET status = ?, points_awarded = ?, ai_response = ?, reviewed_at = datetime('now')
            WHERE id = ?
        """, (status, points, ai_response, completion_id))


def get_completion(completion_id: int):
    with get_conn() as conn:
        row = conn.execute("""
            SELECT tc.*, t.title, t.points_value, u.full_name, u.username
            FROM task_completions tc
            JOIN tasks t ON t.id = tc.task_id
            JOIN users u ON u.user_id = tc.user_id
            WHERE tc.id = ?
        """, (completion_id,)).fetchone()
        return dict(row) if row else None


def has_completed_task(user_id: int, scheduled_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT id FROM task_completions
            WHERE user_id = ? AND scheduled_id = ? AND status = 'approved'
        """, (user_id, scheduled_id)).fetchone()
        return row is not None


def get_pending_completions():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT tc.id, tc.user_id, tc.screenshot_path, tc.submitted_at,
                   t.title, t.points_value, u.full_name, u.username
            FROM task_completions tc
            JOIN tasks t ON t.id = tc.task_id
            JOIN users u ON u.user_id = tc.user_id
            WHERE tc.status = 'pending'
            ORDER BY tc.submitted_at ASC
        """).fetchall()
        return [dict(r) for r in rows]


def get_user_completions(user_id: int, limit: int = 10):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT tc.status, tc.points_awarded, tc.submitted_at, t.title
            FROM task_completions tc
            JOIN tasks t ON t.id = tc.task_id
            WHERE tc.user_id = ?
            ORDER BY tc.submitted_at DESC LIMIT ?
        """, (user_id, limit)).fetchall()
        return [dict(r) for r in rows]


# ─── Rewards ─────────────────────────────────────────────────────────────────

def create_reward(name, description, points_required, provider):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO rewards (name, description, points_required, provider)
            VALUES (?, ?, ?, ?)
        """, (name, description, points_required, provider))
        return cur.lastrowid


def list_rewards(active_only: bool = True):
    with get_conn() as conn:
        q = "SELECT * FROM rewards"
        if active_only:
            q += " WHERE is_active = 1"
        q += " ORDER BY points_required ASC"
        return [dict(r) for r in conn.execute(q).fetchall()]


def get_reward(reward_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM rewards WHERE id = ?", (reward_id,)).fetchone()
        return dict(row) if row else None


def deactivate_reward(reward_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE rewards SET is_active = 0 WHERE id = ?", (reward_id,))


# ─── Redemptions ─────────────────────────────────────────────────────────────

def create_redemption(user_id: int, reward_id: int, points_used: int, voucher_code: str):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO redemptions (user_id, reward_id, points_used, voucher_code)
            VALUES (?, ?, ?, ?)
        """, (user_id, reward_id, points_used, voucher_code))
        return cur.lastrowid


def get_user_redemptions(user_id: int):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT r.name, r.provider, rd.voucher_code, rd.points_used,
                   rd.status, rd.redeemed_at
            FROM redemptions rd
            JOIN rewards r ON r.id = rd.reward_id
            WHERE rd.user_id = ?
            ORDER BY rd.redeemed_at DESC
        """, (user_id,)).fetchall()
        return [dict(r) for r in rows]


def get_redemption_by_code(voucher_code: str):
    with get_conn() as conn:
        row = conn.execute("""
            SELECT rd.*, r.name as reward_name, r.provider,
                   u.full_name, u.username
            FROM redemptions rd
            JOIN rewards r ON r.id = rd.reward_id
            JOIN users u ON u.user_id = rd.user_id
            WHERE rd.voucher_code = ?
        """, (voucher_code,)).fetchone()
        return dict(row) if row else None


def mark_voucher_used(voucher_code: str):
    with get_conn() as conn:
        conn.execute("""
            UPDATE redemptions SET status = 'used', used_at = datetime('now')
            WHERE voucher_code = ?
        """, (voucher_code,))


# ─── Allies (Empresas aliadas) ──────────────────────────────────────────────

def create_ally(business_name, owner_name, phone, email, location, city,
                description, photo_path, instagram, facebook, website, telegram_user="", tasks_per_week=7):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO allies (business_name, owner_name, phone, email, location,
                                city, description, photo_path, instagram, facebook, website, telegram_user, tasks_per_week)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (business_name, owner_name, phone, email, location, city,
              description, photo_path, instagram, facebook, website, telegram_user, tasks_per_week))
        return cur.lastrowid


def add_ally_product(ally_id, name, description, price, photo_path, points_required=0):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO ally_products (ally_id, name, description, price, photo_path, points_required)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (ally_id, name, description, price, photo_path, points_required))
        return cur.lastrowid


def get_product(product_id):
    with get_conn() as conn:
        row = conn.execute("""
            SELECT p.*, a.business_name as provider, a.telegram_user
            FROM ally_products p
            JOIN allies a ON a.id = p.ally_id
            WHERE p.id = ?
        """, (product_id,)).fetchone()
        return dict(row) if row else None


def list_redeemable_products():
    """Lista productos canjeables (con puntos > 0 y activos)."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT p.*, a.business_name as provider
            FROM ally_products p
            JOIN allies a ON a.id = p.ally_id
            WHERE p.points_required > 0 AND p.is_active = 1 AND a.status = 'approved'
            ORDER BY a.business_name, p.points_required ASC
        """).fetchall()
        return [dict(r) for r in rows]


def list_allies(status=None):
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM allies WHERE status = ? ORDER BY created_at DESC",
                (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM allies ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_ally(ally_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM allies WHERE id = ?", (ally_id,)).fetchone()
        return dict(row) if row else None


def get_ally_products(ally_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ally_products WHERE ally_id = ? ORDER BY id",
            (ally_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def update_ally_status(ally_id, status):
    with get_conn() as conn:
        conn.execute(
            "UPDATE allies SET status = ? WHERE id = ?",
            (status, ally_id)
        )


def update_ally(ally_id, **fields):
    allowed = {"business_name", "owner_name", "phone", "email", "location",
               "city", "description", "instagram", "facebook", "website", "telegram_user", "tasks_per_week"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [ally_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE allies SET {set_clause} WHERE id = ?", values)


def get_ally_by_telegram(telegram_user):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM allies WHERE telegram_user = ?",
            (telegram_user.lstrip("@"),)
        ).fetchone()
        return dict(row) if row else None
