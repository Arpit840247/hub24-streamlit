import hashlib
import hmac
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

DB_PATH = os.getenv("HUB24_DB_PATH", "hub24.db")
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feed_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                sender TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'unread',
                priority TEXT NOT NULL DEFAULT 'normal',
                action_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_feed_user_time ON feed_items (user_id, created_at DESC)"
        )
        conn.commit()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_REGEX.match((email or "").strip()))


def validate_password_strength(password: str) -> Tuple[bool, str]:
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[A-Za-z]", password):
        return False, "Password must contain at least one letter (A-Z)."
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number (0-9)."
    return True, ""


def _hash_password(password: str, salt_hex: Optional[str] = None) -> Tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 150_000)
    return digest.hex(), salt.hex()


def create_user(name: str, email: str, password: str) -> Tuple[bool, str]:
    clean_name = (name or "").strip()
    clean_email = (email or "").strip().lower()

    if len(clean_name) < 2:
        return False, "Enter your full name (at least 2 characters)."
    if not is_valid_email(clean_email):
        return False, "Enter a valid email address (e.g., name@gmail.com)."

    ok_pw, pw_msg = validate_password_strength(password)
    if not ok_pw:
        return False, pw_msg

    pw_hash, salt_hex = _hash_password(password)
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (name, email, password_hash, salt, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (clean_name, clean_email, pw_hash, salt_hex, now_iso),
            )
            conn.commit()
        return True, "Account created successfully. You can now log in."
    except sqlite3.IntegrityError:
        return False, "This email is already registered. Please log in."


def authenticate_user(email: str, password: str) -> Tuple[Optional[Dict], str]:
    clean_email = (email or "").strip().lower()
    if not is_valid_email(clean_email):
        return None, "Invalid email format. Enter a proper email address."
    if not password:
        return None, "Password is required."

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, email, password_hash, salt FROM users WHERE email = ?",
            (clean_email,),
        ).fetchone()

    if not row:
        return None, "No account found with this email."

    computed_hash, _ = _hash_password(password, row["salt"])
    if not hmac.compare_digest(computed_hash, row["password_hash"]):
        return None, "Incorrect password."

    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
    }, "Login successful."


def add_feed_item(
    user_id: int,
    channel: str,
    sender: str,
    title: str,
    body: str,
    created_at: Optional[datetime] = None,
    priority: str = "normal",
) -> None:
    ts = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO feed_items (user_id, channel, sender, title, body, status, priority, action_note, created_at)
            VALUES (?, ?, ?, ?, ?, 'unread', ?, '', ?)
            """,
            (
                user_id,
                channel.strip().lower(),
                sender.strip()[:100],
                title.strip()[:140],
                body.strip()[:1000],
                "high" if priority == "high" else "normal",
                ts,
            ),
        )
        conn.commit()


def item_exists(user_id: int, channel: str, title: str, sender: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM feed_items
            WHERE user_id = ? AND channel = ? AND title = ? AND sender = ?
            LIMIT 1
            """,
            (user_id, channel, title.strip()[:140], sender.strip()[:100]),
        ).fetchone()
    return row is not None


def get_feed_items(
    user_id: int,
    channel: Optional[str] = None,
    only_24h: bool = True,
    status_filter: str = "all",
    search_query: str = "",
) -> List[Dict]:
    clauses = ["user_id = ?"]
    params: List = [user_id]

    if channel:
        clauses.append("channel = ?")
        params.append(channel)

    if only_24h:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        clauses.append("created_at >= ?")
        params.append(cutoff)

    if status_filter != "all":
        clauses.append("status = ?")
        params.append(status_filter)

    if search_query.strip():
        q = f"%{search_query.strip()}%"
        clauses.append("(sender LIKE ? OR title LIKE ? OR body LIKE ? OR action_note LIKE ?)")
        params.extend([q, q, q, q])

    where_sql = " AND ".join(clauses)
    query = f"""
        SELECT id, channel, sender, title, body, status, priority, action_note, created_at
        FROM feed_items
        WHERE {where_sql}
        ORDER BY CASE priority WHEN 'high' THEN 0 ELSE 1 END, created_at DESC
    """
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_channel_counts_24h(user_id: int) -> Dict[str, int]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT channel, COUNT(*) AS cnt
            FROM feed_items
            WHERE user_id = ? AND created_at >= ? AND status != 'done'
            GROUP BY channel
            """,
            (user_id, cutoff),
        ).fetchall()
    return {r["channel"]: r["cnt"] for r in rows}


def get_summary_24h(user_id: int) -> Dict[str, int]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS cnt
            FROM feed_items
            WHERE user_id = ? AND created_at >= ?
            GROUP BY status
            """,
            (user_id, cutoff),
        ).fetchall()
    counts = {r["status"]: r["cnt"] for r in rows}
    unread = counts.get("unread", 0)
    followup = counts.get("followup", 0)
    done = counts.get("done", 0)
    return {
        "total_24h": unread + followup + done,
        "unread": unread,
        "followup": followup,
        "done": done,
    }


def update_item_status(user_id: int, item_id: int, new_status: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE feed_items SET status = ? WHERE id = ? AND user_id = ?",
            (new_status, item_id, user_id),
        )
        conn.commit()


def update_action_note(user_id: int, item_id: int, note: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE feed_items SET action_note = ? WHERE id = ? AND user_id = ?",
            (note.strip()[:500], item_id, user_id),
        )
        conn.commit()


def carry_item_24h(user_id: int, item_id: int) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE feed_items SET created_at = ? WHERE id = ? AND user_id = ?",
            (now_iso, item_id, user_id),
        )
        conn.commit()


def delete_item(user_id: int, item_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM feed_items WHERE id = ? AND user_id = ?",
            (item_id, user_id),
        )
        conn.commit()