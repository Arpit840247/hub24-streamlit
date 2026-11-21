import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DB_PATH = Path(__file__).parent / "hub24.db"


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
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
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
                action_note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'unread',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        # Safe migration if upgrading from an older table without action_note
        cols = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(feed_items)").fetchall()
        ]
        if "action_note" not in cols:
            conn.execute(
                "ALTER TABLE feed_items ADD COLUMN action_note TEXT NOT NULL DEFAULT ''"
            )
        conn.commit()


def _hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    ).hex()
    return f"{salt}${digest}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, _ = stored_hash.split("$", 1)
        return secrets.compare_digest(_hash_password(password, salt), stored_hash)
    except ValueError:
        return False


def create_user(name: str, email: str, password: str) -> Tuple[bool, str]:
    name = name.strip()
    email = email.strip().lower()
    if not name or not email or len(password) < 4:
        return False, "Please enter name, valid email, and a password (min 4 chars)."

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (name, email, _hash_password(password), now_iso),
            )
            conn.commit()
        return True, "Account created! Please log in."
    except sqlite3.IntegrityError:
        return False, "An account with this email already exists."


def authenticate_user(email: str, password: str) -> Optional[Dict]:
    email = email.strip().lower()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    if row and _verify_password(password, row["password_hash"]):
        return {"id": row["id"], "name": row["name"], "email": row["email"]}
    return None


def item_exists(user_id: int, channel: str, title: str, sender: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM feed_items
            WHERE user_id = ? AND channel = ? AND LOWER(title) = LOWER(?) AND LOWER(sender) = LOWER(?)
            LIMIT 1
            """,
            (user_id, channel.lower(), title.strip(), sender.strip()),
        ).fetchone()
    return row is not None


def add_feed_item(
    user_id: int,
    channel: str,
    sender: str,
    title: str,
    body: str,
    created_at: Optional[datetime] = None,
) -> None:
    ts = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO feed_items (user_id, channel, sender, title, body, action_note, status, created_at)
            VALUES (?, ?, ?, ?, ?, '', 'unread', ?)
            """,
            (user_id, channel.lower(), sender.strip(), title.strip(), body.strip(), ts),
        )
        conn.commit()


def get_channel_counts_24h(user_id: int) -> Dict[str, int]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT channel, COUNT(*) as cnt
            FROM feed_items
            WHERE user_id = ? AND created_at >= ? AND status != 'done'
            GROUP BY channel
            """,
            (user_id, cutoff),
        ).fetchall()
    return {row["channel"]: row["cnt"] for row in rows}


def get_summary_24h(user_id: int) -> Dict[str, int]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) as cnt
            FROM feed_items
            WHERE user_id = ? AND created_at >= ?
            GROUP BY status
            """,
            (user_id, cutoff),
        ).fetchall()
    counts = {"unread": 0, "followup": 0, "done": 0}
    for r in rows:
        counts[r["status"]] = r["cnt"]
    counts["total_24h"] = sum(counts.values())
    return counts


def get_feed_items(
    user_id: int,
    channel: Optional[str] = None,
    only_24h: bool = True,
    status_filter: str = "all",
    search_query: str = "",
) -> List[Dict]:
    query = "SELECT * FROM feed_items WHERE user_id = ?"
    params: List = [user_id]

    if channel and channel != "all":
        query += " AND channel = ?"
        params.append(channel.lower())

    if only_24h:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        query += " AND created_at >= ?"
        params.append(cutoff)

    if status_filter != "all":
        query += " AND status = ?"
        params.append(status_filter)

    if search_query.strip():
        like_q = f"%{search_query.strip()}%"
        query += " AND (LOWER(title) LIKE LOWER(?) OR LOWER(body) LIKE LOWER(?) OR LOWER(sender) LIKE LOWER(?) OR LOWER(action_note) LIKE LOWER(?))"
        params.extend([like_q, like_q, like_q, like_q])

    query += " ORDER BY created_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


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
            (note.strip(), item_id, user_id),
        )
        conn.commit()


def delete_item(user_id: int, item_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM feed_items WHERE id = ? AND user_id = ?",
            (item_id, user_id),
        )
        conn.commit()