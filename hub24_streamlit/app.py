from datetime import datetime, timezone
import os
from typing import Dict, List, Tuple
import streamlit as st

from connectors import (
    CHANNELS,
    extract_email_address,
    fetch_recent_emails_24h,
    get_channel_map,
    send_email_smtp,
)
from database import (
    add_feed_item,
    authenticate_user,
    carry_item_24h,
    create_user,
    delete_item,
    get_channel_counts_24h,
    get_feed_items,
    get_summary_24h,
    init_db,
    item_exists,
    update_action_note,
    update_item_status,
)

st.set_page_config(
    page_title="Hub24 — 24h Command & Activity Workspace",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

init_db()

if "user" not in st.session_state:
    st.session_state.user = None
if "selected_channel" not in st.session_state:
    st.session_state.selected_channel = "whatsapp"
if "imap_email" not in st.session_state:
    st.session_state.imap_email = os.getenv("IMAP_EMAIL", "")
if "imap_password" not in st.session_state:
    st.session_state.imap_password = os.getenv("IMAP_APP_PASSWORD", "")
if "imap_host" not in st.session_state:
    st.session_state.imap_host = os.getenv("IMAP_HOST", "imap.gmail.com")
if "smtp_host" not in st.session_state:
    st.session_state.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")


def inject_theme_css() -> None:
    st.markdown(
        """
        <style>
            :root {
                --bg-main: #090d16;
                --bg-surface: #111827;
                --bg-elevated: #172033;
                --border-subtle: rgba(148, 163, 184, 0.16);
                --text-primary: #f1f5f9;
                --text-muted: #94a3b8;
            }

            .stApp {
                background: radial-gradient(circle at top right, #111c33 0%, #090d16 55%, #070a12 100%);
                color: var(--text-primary);
            }

            [data-testid="stHeader"] {
                background: rgba(9, 13, 22, 0.75);
                backdrop-filter: blur(10px);
            }

            [data-testid="stMetric"] {
                background: linear-gradient(145deg, rgba(23, 32, 51, 0.92), rgba(15, 23, 42, 0.85));
                border: 1px solid var(--border-subtle);
                border-radius: 14px;
                padding: 14px 16px;
                box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
            }

            [data-testid="stMetricLabel"] {
                color: var(--text-muted) !important;
                font-weight: 500;
            }

            [data-testid="stMetricValue"] {
                color: var(--text-primary) !important;
                font-weight: 700;
            }

            [data-testid="stVerticalBlockBorderWrapper"] {
                background: rgba(17, 24, 39, 0.82);
                border: 1px solid var(--border-subtle) !important;
                border-radius: 14px !important;
                padding: 4px 8px;
                box-shadow: 0 6px 20px rgba(0, 0, 0, 0.22);
            }

            .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div {
                background-color: #0d1424 !important;
                color: #f8fafc !important;
                border-color: rgba(148, 163, 184, 0.24) !important;
                border-radius: 10px !important;
            }

            .stButton button[kind="primary"], .stFormSubmitButton button[kind="primary"] {
                background: linear-gradient(135deg, #0284c7, #2563eb) !important;
                color: #ffffff !important;
                border: none !important;
                border-radius: 10px !important;
                font-weight: 600 !important;
            }

            .stButton button[kind="secondary"], .stFormSubmitButton button[kind="secondary"] {
                background: #172033 !important;
                color: #e2e8f0 !important;
                border: 1px solid rgba(148, 163, 184, 0.22) !important;
                border-radius: 10px !important;
            }

            .hub-banner {
                background: linear-gradient(120deg, rgba(14, 165, 233, 0.14), rgba(37, 99, 235, 0.10));
                border: 1px solid rgba(56, 189, 248, 0.24);
                border-radius: 16px;
                padding: 16px 20px;
                margin-bottom: 14px;
            }

            @media (max-width: 768px) {
                .block-container {
                    padding-top: 1rem !important;
                    padding-left: 0.75rem !important;
                    padding-right: 0.75rem !important;
                    padding-bottom: 2.5rem !important;
                }

                .hub-banner {
                    padding: 12px 14px;
                    border-radius: 12px;
                }

                [data-testid="stMetric"] {
                    padding: 10px 12px;
                    border-radius: 12px;
                }

                .stButton button, .stFormSubmitButton button {
                    min-height: 42px;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_theme_css()


def format_timestamp(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str).astimezone()
        return dt.strftime("%d %b, %I:%M %p")
    except Exception:
        return iso_str


def parse_quick_command(
    raw_text: str, default_channel: str
) -> Tuple[str, str, str, str, str]:
    text = raw_text.strip()
    lower = text.lower()

    priority = (
        "high"
        if any(k in lower.split() for k in {"urgent", "asap", "high", "critical"})
        else "normal"
    )

    detected_channel = default_channel
    if lower.startswith(("call ", "phone ", "ring ")):
        detected_channel = "calls"
    elif lower.startswith(("email ", "mail ", "send email ")):
        detected_channel = "email"
    elif lower.startswith(("whatsapp ", "wa ", "msg ", "message ", "text ")):
        detected_channel = "whatsapp"
    elif lower.startswith(("task ", "todo ", "remind ", "study ", "sleep ", "routine ")):
        detected_channel = "tasks"

    sender = "Direct Command"
    title = text
    body = text

    if ":" in text:
        left, right = text.split(":", 1)
        if right.strip():
            sender = left.strip()[:40]
            title = right.strip()[:80]
            body = right.strip()
            return detected_channel, sender, title, body, priority

    parts = text.split(" ", 2)
    if len(parts) >= 2 and parts[0].lower() in {
        "call",
        "phone",
        "ring",
        "email",
        "mail",
        "whatsapp",
        "wa",
        "msg",
        "message",
        "text",
        "task",
        "todo",
        "remind",
        "study",
        "sleep",
        "routine",
    }:
        sender = parts[1].strip()[:40] or "Direct Command"
        title = text[:80]
        body = text

    return detected_channel, sender, title, body, priority


def build_digest_markdown(user_name: str, items: List[Dict]) -> str:
    now_label = datetime.now().astimezone().strftime("%d %b %Y, %I:%M %p")
    lines = [
        "# Hub24 — 24-Hour Activity Digest",
        f"**Workspace:** {user_name}  ",
        f"**Generated:** {now_label}  ",
        f"**Total Items:** {len(items)}",
        "",
    ]
    if not items:
        lines.append("_No items recorded in this view._")
        return "\n".join(lines)

    for idx, it in enumerate(items, start=1):
        prio = " [HIGH PRIORITY]" if it.get("priority") == "high" else ""
        lines.append(f"## {idx}. [{it['channel'].upper()}] {it['title']}{prio}")
        lines.append(f"- **Source / Contact:** {it['sender']}")
        lines.append(f"- **Status:** {it['status']}")
        lines.append(f"- **Time:** {format_timestamp(it['created_at'])}")
        lines.append(f"- **Details:** {it['body']}")
        if it.get("action_note"):
            lines.append(f"- **Action / Reply Log:** {it['action_note']}")
        lines.append("")
    return "\n".join(lines)


def render_auth_screen() -> None:
    left_spacer, center_col, right_spacer = st.columns([1, 2, 1])
    with center_col:
        st.markdown(
            """
            <div class="hub-banner">
                <h2 style="margin:0;">⚡ Hub24</h2>
                <p style="margin:6px 0 0 0; color:#cbd5e1;">
                    24-hour personal command &amp; unified activity workspace. Sign in or create an account to begin.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        tab_login, tab_signup = st.tabs(["Login", "Sign Up"])

        with tab_login:
            with st.form("login_form"):
                email_input = st.text_input("Email")
                password_input = st.text_input("Password", type="password")
                submitted = st.form_submit_button(
                    "Login", use_container_width=True, type="primary"
                )
                if submitted:
                    user = authenticate_user(email_input, password_input)
                    if user:
                        st.session_state.user = user
                        st.rerun()
                    else:
                        st.error("Invalid email or password.")

        with tab_signup:
            with st.form("signup_form"):
                name_input = st.text_input("Full Name")
                email_input = st.text_input("Email", key="signup_email")
                password_input = st.text_input(
                    "Create Password (min 4 chars)", type="password", key="signup_pw"
                )
                submitted = st.form_submit_button("Create Account", use_container_width=True)
                if submitted:
                    ok, msg = create_user(name_input, email_input, password_input)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)


def render_dashboard() -> None:
    user: dict = st.session_state.user
    channel_map = get_channel_map()
    counts_24h = get_channel_counts_24h(user["id"])
    summary = get_summary_24h(user["id"])

    col_title, col_logout = st.columns([5, 1.2])
    with col_title:
        st.markdown(
            f"""
            <div class="hub-banner">
                <h2 style="margin:0;">⚡ Hub24 Command Center</h2>
                <p style="margin:4px 0 0 0; color:#cbd5e1;">
                    Workspace: <strong>{user['name']}</strong> &nbsp;•&nbsp; Active Window: <strong>Last 24 Hours</strong>
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_logout:
        st.write("")
        if st.button("Logout", use_container_width=True):
            st.session_state.user = None
            st.rerun()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Last 24h Items", summary["total_24h"])
    m2.metric("Unread", summary["unread"])
    m3.metric("Follow-ups", summary["followup"])
    m4.metric("Completed (24h)", summary["done"])

    st.write("")
    with st.form("smart_command_form", clear_on_submit=True):
        cmd_col, btn_col = st.columns([4.5, 1.1])
        with cmd_col:
            command_text = st.text_input(
                "Command Input",
                label_visibility="collapsed",
                placeholder="Command bar: e.g. 'urgent call Rahul at 5pm', 'email HR about interview', 'whatsapp Rohan: 6pm review', or 'task revise SQL'",
            )
        with btn_col:
            run_cmd = st.form_submit_button(
                "⚡ Execute", use_container_width=True, type="primary"
            )

        if run_cmd:
            if command_text.strip():
                ch_id, sender, title, body, priority = parse_quick_command(
                    command_text, st.session_state.selected_channel
                )
                add_feed_item(
                    user_id=user["id"],
                    channel=ch_id,
                    sender=sender,
                    title=title,
                    body=body,
                    created_at=datetime.now(timezone.utc),
                    priority=priority,
                )
                st.session_state.selected_channel = ch_id
                st.toast(f"Added to {channel_map[ch_id]['name']}")
                st.rerun()
            else:
                st.warning("Please enter a command first.")

    st.divider()

    st.subheader("Apps & Channels")
    cols = st.columns(len(CHANNELS))
    for idx, ch in enumerate(CHANNELS):
        ch_id = ch["id"]
        pending_count = counts_24h.get(ch_id, 0)
        is_selected = st.session_state.selected_channel == ch_id
        with cols[idx]:
            with st.container(border=True):
                st.markdown(f"### {ch['icon']} {ch['name']}")
                st.caption(ch["subtitle"])
                st.metric(label="Open (24h)", value=pending_count)
                btn_label = f"● {ch['name']} Active" if is_selected else f"Open {ch['name']}"
                if st.button(
                    btn_label,
                    key=f"btn_ch_{ch_id}",
                    use_container_width=True,
                    type="primary" if is_selected else "secondary",
                ):
                    st.session_state.selected_channel = ch_id
                    st.rerun()

    st.divider()

    feed_col, side_col = st.columns([2.25, 1.15])

    with feed_col:
        active_ch = channel_map.get(st.session_state.selected_channel, CHANNELS[0])

        f1, f2, f3 = st.columns([1.1, 1.1, 1.5])
        with f1:
            only_24h = st.toggle("Last 24h Only", value=True)
        with f2:
            scope_all_channels = st.toggle("All Channels", value=False)
        with f3:
            status_filter = st.selectbox(
                "Filter by Status",
                options=["all", "unread", "followup", "done"],
                label_visibility="collapsed",
            )

        search_q = st.text_input(
            "Search items",
            label_visibility="collapsed",
            placeholder="Search sender, subject, details, or action notes...",
        )

        heading_label = (
            "🌐 All Channels — Unified Feed"
            if scope_all_channels
            else f"{active_ch['icon']} {active_ch['name']} — Feed"
        )
        st.subheader(heading_label)

        items = get_feed_items(
            user_id=user["id"],
            channel=None if scope_all_channels else active_ch["id"],
            only_24h=only_24h,
            status_filter=status_filter,
            search_query=search_q,
        )

        st.download_button(
            label="📄 Export Current View Digest (.md)",
            data=build_digest_markdown(user["name"], items),
            file_name=f"hub24_digest_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
            mime="text/markdown",
            use_container_width=False,
        )

        if not items:
            st.info(
                "No items in this view. Execute a command above, create a new entry, or sync your last-24h inbox."
            )
        else:
            for item in items:
                status_tag = {
                    "unread": "🔵 Unread",
                    "followup": "🟡 Follow-up",
                    "done": "✅ Done",
                }.get(item["status"], item["status"])
                prio_badge = " • 🔥 High" if item.get("priority") == "high" else ""

                with st.container(border=True):
                    header_a, header_b = st.columns([3.4, 1.4])
                    with header_a:
                        prefix = (
                            f"**[{channel_map.get(item['channel'], {}).get('name', item['channel']).upper()}]** "
                            if scope_all_channels
                            else ""
                        )
                        title_display = (
                            f"~~{item['title']}~~"
                            if item["status"] == "done"
                            else f"**{item['title']}**"
                        )
                        st.markdown(f"{prefix}{title_display}")
                        st.caption(f"Source / Contact: **{item['sender']}**{prio_badge}")
                    with header_b:
                        st.caption(f"{status_tag}\n{format_timestamp(item['created_at'])}")

                    st.write(item["body"])

                    saved_note = item.get("action_note", "")
                    if saved_note:
                        st.info(f"📝 Action / Reply Log: {saved_note}")

                    with st.expander("✍️ Action Note / Reply Draft", expanded=False):
                        note_val = st.text_input(
                            "Action note or reply draft",
                            value=saved_note,
                            key=f"note_input_{item['id']}",
                            placeholder="Write next action or reply draft...",
                        )
                        if st.button("Save Note", key=f"save_note_{item['id']}"):
                            update_action_note(user["id"], item["id"], note_val)
                            st.toast("Action note saved")
                            st.rerun()

                    if item["channel"] == "email":
                        detected_to = extract_email_address(item["sender"])
                        with st.expander("📤 Send Email / Reply (SMTP)", expanded=False):
                            to_addr = st.text_input(
                                "To",
                                value=detected_to,
                                key=f"smtp_to_{item['id']}",
                            )
                            subj_default = (
                                item["title"]
                                if item["title"].lower().startswith("re:")
                                else f"Re: {item['title']}"
                            )
                            subj_val = st.text_input(
                                "Subject",
                                value=subj_default,
                                key=f"smtp_subj_{item['id']}",
                            )
                            msg_val = st.text_area(
                                "Message",
                                key=f"smtp_msg_{item['id']}",
                                placeholder="Write your reply...",
                            )
                            mark_done_after = st.checkbox(
                                "Mark item as Done after sending",
                                value=True,
                                key=f"smtp_done_{item['id']}",
                            )
                            if st.button(
                                "Send Email", key=f"smtp_send_{item['id']}", type="primary"
                            ):
                                ok_send, send_msg = send_email_smtp(
                                    sender_email=st.session_state.imap_email,
                                    app_password=st.session_state.imap_password,
                                    to_email=to_addr,
                                    subject=subj_val,
                                    message_text=msg_val,
                                    smtp_host=st.session_state.smtp_host,
                                )
                                if ok_send:
                                    log_txt = f"Sent to {to_addr}: {msg_val.strip()[:120]}"
                                    combined_note = f"{saved_note} | {log_txt}".strip(" |")
                                    update_action_note(user["id"], item["id"], combined_note)
                                    if mark_done_after:
                                        update_item_status(user["id"], item["id"], "done")
                                    st.success(send_msg)
                                    st.rerun()
                                else:
                                    st.error(send_msg)

                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        if st.button(
                            "Done",
                            key=f"done_{item['id']}",
                            use_container_width=True,
                            disabled=(item["status"] == "done"),
                        ):
                            update_item_status(user["id"], item["id"], "done")
                            st.rerun()
                    with c2:
                        if st.button(
                            "Follow-up",
                            key=f"fu_{item['id']}",
                            use_container_width=True,
                            disabled=(item["status"] == "followup"),
                        ):
                            update_item_status(user["id"], item["id"], "followup")
                            st.rerun()
                    with c3:
                        if st.button(
                            "Carry +24h",
                            key=f"carry_{item['id']}",
                            use_container_width=True,
                        ):
                            carry_item_24h(user["id"], item["id"])
                            st.toast("Carried forward for another 24h")
                            st.rerun()
                    with c4:
                        if st.button("Delete", key=f"del_{item['id']}", use_container_width=True):
                            delete_item(user["id"], item["id"])
                            st.rerun()

    with side_col:
        with st.container(border=True):
            st.subheader("📬 Live 24h Email Sync")
            st.caption("Sync last-24h inbox emails (session-only credentials).")
            with st.form("email_sync_form"):
                imap_user = st.text_input(
                    "Email Address",
                    value=st.session_state.imap_email,
                    placeholder="you@gmail.com",
                )
                imap_pass = st.text_input(
                    "App Password",
                    value=st.session_state.imap_password,
                    type="password",
                    placeholder="16-char app password",
                )
                imap_srv = st.text_input("IMAP Host", value=st.session_state.imap_host)
                smtp_srv = st.text_input("SMTP Host", value=st.session_state.smtp_host)
                sync_clicked = st.form_submit_button(
                    "Sync Last 24h Emails", use_container_width=True, type="primary"
                )

                if sync_clicked:
                    st.session_state.imap_email = imap_user
                    st.session_state.imap_password = imap_pass
                    st.session_state.imap_host = imap_srv
                    st.session_state.smtp_host = smtp_srv

                    ok, msg, fetched = fetch_recent_emails_24h(imap_user, imap_pass, imap_srv)
                    if not ok:
                        st.error(msg)
                    else:
                        new_count = 0
                        for mail_item in fetched:
                            if not item_exists(
                                user["id"], "email", mail_item["title"], mail_item["sender"]
                            ):
                                add_feed_item(
                                    user_id=user["id"],
                                    channel="email",
                                    sender=mail_item["sender"],
                                    title=mail_item["title"],
                                    body=mail_item["body"],
                                    created_at=mail_item["created_at"],
                                )
                                new_count += 1
                        st.success(f"{msg} ({new_count} new saved)")
                        st.session_state.selected_channel = "email"
                        st.rerun()

        st.write("")
        with st.container(border=True):
            st.subheader("➕ New Entry")
            with st.form("detailed_add_form", clear_on_submit=True):
                target_channel = st.selectbox(
                    "Channel",
                    options=[c["id"] for c in CHANNELS],
                    index=[c["id"] for c in CHANNELS].index(st.session_state.selected_channel),
                    format_func=lambda cid: f"{channel_map[cid]['icon']} {channel_map[cid]['name']}",
                )
                priority_choice = st.selectbox(
                    "Priority",
                    options=["normal", "high"],
                    format_func=lambda p: "🔥 High Priority" if p == "high" else "Normal",
                )
                sender = st.text_input("Source / Contact", placeholder="e.g., Client, Team, Routine")
                title = st.text_input("Title / Subject", placeholder="e.g., Follow up on deliverable")
                body = st.text_area("Details", placeholder="Write message, call log, or task details...")
                submitted = st.form_submit_button("Save Entry", use_container_width=True)

                if submitted:
                    if sender.strip() and title.strip() and body.strip():
                        add_feed_item(
                            user_id=user["id"],
                            channel=target_channel,
                            sender=sender,
                            title=title,
                            body=body,
                            created_at=datetime.now(timezone.utc),
                            priority=priority_choice,
                        )
                        st.success("Saved")
                        st.rerun()
                    else:
                        st.warning("Please fill in source, title, and details.")


if st.session_state.user:
    render_dashboard()
else:
    render_auth_screen()
