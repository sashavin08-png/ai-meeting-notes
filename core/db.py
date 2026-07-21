"""
Database layer for AI Meeting Notes.

Two tables:
  users    — real accounts, one row per registered person, passwords
             stored as salted hashes (never plain text)
  meetings — one row per uploaded audio file, belonging to exactly one user

SQLite for local development. Same pattern as the receptionist platform:
switches to Postgres automatically when DATABASE_URL is set, so this is
ready for a real cloud deploy later without rewriting anything here.
"""

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                    TEXT PRIMARY KEY,
    email                 TEXT UNIQUE NOT NULL,
    password_hash         TEXT NOT NULL,
    plan                  TEXT NOT NULL DEFAULT 'free',
    stripe_customer_id    TEXT,
    stripe_subscription_id TEXT,
    created_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meetings (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    title           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'processing',
    transcript      TEXT,
    summary         TEXT,
    action_items    TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meetings_user ON meetings(user_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _using_postgres() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


class _PGConn:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, query: str, params=()):
        cur = self._conn.cursor()
        cur.execute(query.replace("?", "%s"), params)
        return cur

    def executescript(self, script: str):
        cur = self._conn.cursor()
        cur.execute(script)


@contextmanager
def get_conn():
    if _using_postgres():
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(
            os.environ["DATABASE_URL"],
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        wrapper = _PGConn(conn)
        try:
            yield wrapper
            conn.commit()
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    _run_migrations()


def _run_migrations():
    """
    Adds columns that didn't exist in earlier versions of this schema, so
    a database created in Session 1 (before Stripe fields existed) still
    works after upgrading — same pattern used in the receptionist platform.
    """
    for statement in (
        "ALTER TABLE users ADD COLUMN stripe_customer_id TEXT",
        "ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT",
    ):
        try:
            with get_conn() as conn:
                conn.execute(statement)
        except Exception:
            pass  # column already exists


# ---------- Users ----------

def create_user(email: str, password_hash: str) -> str:
    user_id = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, plan, created_at) VALUES (?, ?, ?, 'free', ?)",
            (user_id, email.lower().strip(), password_hash, now_iso()),
        )
    return user_id


def get_user_by_email(email: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
        ).fetchone()


def get_user(user_id: str):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_stripe_customer_id(stripe_customer_id: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE stripe_customer_id = ?", (stripe_customer_id,)
        ).fetchone()


def set_stripe_customer_id(user_id: str, stripe_customer_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET stripe_customer_id = ? WHERE id = ?", (stripe_customer_id, user_id)
        )


def set_user_plan(user_id: str, plan: str, stripe_subscription_id: str | None = None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET plan = ?, stripe_subscription_id = ? WHERE id = ?",
            (plan, stripe_subscription_id, user_id),
        )


# ---------- Meetings ----------

def create_meeting(user_id: str, title: str) -> str:
    meeting_id = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO meetings (id, user_id, title, status, created_at) VALUES (?, ?, ?, 'processing', ?)",
            (meeting_id, user_id, title, now_iso()),
        )
    return meeting_id


def update_meeting_result(meeting_id: str, transcript: str, summary: str, action_items: str):
    with get_conn() as conn:
        conn.execute(
            """UPDATE meetings SET status = 'done', transcript = ?, summary = ?, action_items = ?
               WHERE id = ?""",
            (transcript, summary, action_items, meeting_id),
        )


def mark_meeting_failed(meeting_id: str, error_message: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE meetings SET status = 'failed', summary = ? WHERE id = ?",
            (error_message, meeting_id),
        )


def get_meeting(meeting_id: str):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()


def list_meetings(user_id: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM meetings WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()


def count_meetings_this_month(user_id: str) -> int:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT created_at FROM meetings WHERE user_id = ?", (user_id,)
        ).fetchall()
    current_month = now_iso()[:7]  # 'YYYY-MM'
    return sum(1 for r in rows if r["created_at"][:7] == current_month)
