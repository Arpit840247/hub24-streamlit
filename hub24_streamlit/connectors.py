import email
from email.header import decode_header
import imaplib
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

CHANNELS: List[Dict[str, str]] = [
    {
        "id": "whatsapp",
        "name": "WhatsApp",
        "subtitle": "Last 24h messages, logs & replies",
        "icon": "💬",
    },
    {
        "id": "email",
        "name": "Email",
        "subtitle": "Live last-24h inbox & threads",
        "icon": "📧",
    },
    {
        "id": "calls",
        "name": "Phone & Calls",
        "subtitle": "Last 24h call logs & callbacks",
        "icon": "📞",
    },
    {
        "id": "tasks",
        "name": "Tasks & Routine",
        "subtitle": "Last 24h tasks, study & schedule blocks",
        "icon": "✅",
    },
]


def get_channel_map() -> Dict[str, Dict[str, str]]:
    return {ch["id"]: ch for ch in CHANNELS}


def _decode_str(value: Optional[str]) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out).strip()


def _extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace").strip()
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace").strip()
    return "(No plain-text preview available)"


def fetch_recent_emails_24h(
    email_addr: str,
    app_password: str,
    imap_host: str = "imap.gmail.com",
    limit: int = 25,
) -> Tuple[bool, str, List[Dict]]:
    """Fetches INBOX emails received in the last 24 hours via IMAP over SSL."""
    if not email_addr or not app_password:
        return False, "Email address and App Password are required.", []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    imap_since_date = (cutoff - timedelta(days=1)).strftime("%d-%b-%Y")

    items: List[Dict] = []
    try:
        mail = imaplib.IMAP4_SSL(imap_host, 993, timeout=15)
        mail.login(email_addr.strip(), app_password.strip())
        mail.select("INBOX", readonly=True)

        status, data = mail.search(None, f'(SINCE "{imap_since_date}")')
        if status != "OK" or not data or not data[0]:
            mail.logout()
            return True, "Connected, but no recent emails found.", []

        msg_ids = data[0].split()[-limit:]
        for msg_id in reversed(msg_ids):
            res, msg_data = mail.fetch(msg_id, "(RFC822)")
            if res != "OK" or not msg_data or not msg_data[0]:
                continue
            raw_email = msg_data[0][1]
            if not isinstance(raw_email, bytes):
                continue

            msg = email.message_from_bytes(raw_email)
            date_hdr = msg.get("Date")
            try:
                dt = email.utils.parsedate_to_datetime(date_hdr)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
            except Exception:
                dt = datetime.now(timezone.utc)

            if dt < cutoff:
                continue

            sender = _decode_str(msg.get("From")) or "Unknown Sender"
            subject = _decode_str(msg.get("Subject")) or "(No Subject)"
            body_text = _extract_body(msg)
            snippet = " ".join(body_text.split())[:300]

            items.append(
                {
                    "channel": "email",
                    "sender": sender[:100],
                    "title": subject[:140],
                    "body": snippet or "(Empty message)",
                    "created_at": dt,
                }
            )

        mail.logout()
        return True, f"Synced {len(items)} email(s) from the last 24 hours.", items
    except imaplib.IMAP4.error as exc:
        return False, f"IMAP login/auth failed: {exc}", []
    except Exception as exc:
        return False, f"Could not sync email: {exc}", []