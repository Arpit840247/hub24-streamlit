from datetime import datetime, timedelta, timezone
from typing import Dict, List

CHANNELS: List[Dict[str, str]] = [
    {
        "id": "whatsapp",
        "name": "WhatsApp",
        "subtitle": "Last 24h chats & quick replies",
        "icon": "💬",
    },
    {
        "id": "email",
        "name": "Email",
        "subtitle": "Last 24h inbox & threads",
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
        "subtitle": "Last 24h reminders & study/work blocks",
        "icon": "✅",
    },
]


def get_channel_map() -> Dict[str, Dict[str, str]]:
    return {ch["id"]: ch for ch in CHANNELS}


def get_sample_24h_items() -> List[Dict]:
    now = datetime.now(timezone.utc)
    return [
        {
            "channel": "whatsapp",
            "sender": "Rohan Sharma",
            "title": "Project demo timing",
            "body": "Hey, can we review the prototype around 6 PM today?",
            "created_at": now - timedelta(hours=2),
        },
        {
            "channel": "whatsapp",
            "sender": "Dev Group",
            "title": "Build notes & links",
            "body": "Shared the updated deployment checklist in the group.",
            "created_at": now - timedelta(hours=7),
        },
        {
            "channel": "email",
            "sender": "HR / Talent Team",
            "title": "Interview availability confirmation",
            "body": "Please confirm your preferred slot for the technical round.",
            "created_at": now - timedelta(hours=4),
        },
        {
            "channel": "email",
            "sender": "Cloud Billing",
            "title": "Monthly usage statement",
            "body": "Your current workspace usage is well within free tier limits.",
            "created_at": now - timedelta(hours=14),
        },
        {
            "channel": "calls",
            "sender": "+91 98XXX XXXXX",
            "title": "Missed incoming call",
            "body": "Call missed 3 hours ago — call back to confirm delivery/meeting.",
            "created_at": now - timedelta(hours=3),
        },
        {
            "channel": "tasks",
            "sender": "Personal Routine",
            "title": "Core build sprint + evening revision",
            "body": "Complete 24h feed filter and test deployment flow.",
            "created_at": now - timedelta(hours=1),
        },
    ]