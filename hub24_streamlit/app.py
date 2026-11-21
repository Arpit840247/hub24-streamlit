from datetime import datetime, timezone
import streamlit as st

from connectors import CHANNELS, get_channel_map
from database import (
    add_feed_item,
    authenticate_user,
    create_user,
    delete_item,
    get_channel_counts_24h,
    get_feed_items,
    init_db,
    update_item_status,
)

st.set_page_config(
    page_title="Hub24 — 24h Unified Activity Hub",
    page_icon="⚡",
    layout="wide",
)

init_db()

if "user" not in st.session_state:
    st.session_state.user = None
if "selected_channel" not in st.session_state:
    st.session_state.selected_channel = "whatsapp"


def format_timestamp(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str).astimezone()
        return dt.strftime("%d %b, %I:%M %p")
    except Exception:
        return iso_str


def render_auth_screen() -> None:
    st.title("⚡ Hub24 — 24-Hour Personal Activity Hub")
    st.caption(
        "Sign up or log in to view your apps, inspect the last 24 hours of activity, and take quick actions."
    )

    tab_login, tab_signup = st.tabs(["Login", "Sign Up"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)
            if submitted:
                user = authenticate_user(email, password)
                if user:
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("Invalid email or password.")

    with tab_signup:
        with st.form("signup_form"):
            name = st.text_input("Full Name")
            email = st.text_input("Email", key="signup_email")
            password = st.text_input("Create Password (min 4 chars)", type="password", key="signup_pw")
            submitted = st.form_submit_button("Create Account", use_container_width=True)
            if submitted:
                ok, msg = create_user(name, email, password)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)


def render_dashboard() -> None:
    user = st.session_state.user
    channel_map = get_channel_map()
    counts_24h = get_channel_counts_24h(user["id"])

    col_title, col_actions = st.columns([4, 1])
    with col_title:
        st.title("⚡ Hub24")
        st.caption(f"Logged in as **{user['name']}** ({user['email']}) • Showing **Last 24 Hours** by default")
    with col_actions:
        st.write("")
        if st.button("Logout", use_container_width=True):
            st.session_state.user = None
            st.rerun()

    st.divider()

    st.subheader("Your Connected Apps & Channels")
    cols = st.columns(len(CHANNELS))
    for idx, ch in enumerate(CHANNELS):
        ch_id = ch["id"]
        pending_count = counts_24h.get(ch_id, 0)
        is_selected = st.session_state.selected_channel == ch_id
        with cols[idx]:
            st.markdown(f"### {ch['icon']} {ch['name']}")
            st.caption(ch["subtitle"])
            st.metric(label="Active (24h)", value=pending_count)
            btn_label = f"Viewing {ch['name']}" if is_selected else f"Open {ch['name']}"
            if st.button(
                btn_label,
                key=f"btn_ch_{ch_id}",
                use_container_width=True,
                type="primary" if is_selected else "secondary",
            ):
                st.session_state.selected_channel = ch_id
                st.rerun()

    st.divider()

    feed_col, capture_col = st.columns([2.2, 1])

    with feed_col:
        active_ch = channel_map.get(st.session_state.selected_channel, CHANNELS[0])
        st.subheader(f"{active_ch['icon']} {active_ch['name']} — Activity Feed")

        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            only_24h = st.toggle("Only Last 24 Hours", value=True)
        with filter_col2:
            status_filter = st.selectbox("Status", options=["all", "unread", "followup", "done"])
        with filter_col3:
            scope_all_channels = st.toggle("All Channels Together", value=False)

        items = get_feed_items(
            user_id=user["id"],
            channel=None if scope_all_channels else active_ch["id"],
            only_24h=only_24h,
            status_filter=status_filter,
        )

        if not items:
            st.info("No items match this filter yet. Add a new item on the right or load sample 24h data.")
        else:
            for item in items:
                badge = {
                    "unread": "🔵 Unread",
                    "followup": "🟡 Follow-up",
                    "done": "🟢 Done",
                }.get(item["status"], item["status"])

                with st.container(border=True):
                    top_a, top_b = st.columns([3, 1])
                    with top_a:
                        ch_label = f"[{item['channel'].upper()}] " if scope_all_channels else ""
                        st.markdown(f"**{ch_label}{item['title']}** — *from {item['sender']}*")
                    with top_b:
                        st.caption(f"{badge} • {format_timestamp(item['created_at'])}")

                    st.write(item["body"])

                    act1, act2, act3, act4 = st.columns(4)
                    with act1:
                        if st.button("Mark Done", key=f"done_{item['id']}", use_container_width=True):
                            update_item_status(user["id"], item["id"], "done")
                            st.rerun()
                    with act2:
                        if st.button("Follow-up", key=f"fu_{item['id']}", use_container_width=True):
                            update_item_status(user["id"], item["id"], "followup")
                            st.rerun()
                    with act3:
                        if st.button("Unread", key=f"un_{item['id']}", use_container_width=True):
                            update_item_status(user["id"], item["id"], "unread")
                            st.rerun()
                    with act4:
                        if st.button("Delete", key=f"del_{item['id']}", use_container_width=True):
                            delete_item(user["id"], item["id"])
                            st.rerun()

    with capture_col:
        st.subheader("➕ Quick Add / Test Item")
        with st.form("quick_add_form", clear_on_submit=True):
            target_channel = st.selectbox(
                "Channel",
                options=[c["id"] for c in CHANNELS],
                index=[c["id"] for c in CHANNELS].index(st.session_state.selected_channel),
                format_func=lambda cid: f"{channel_map[cid]['icon']} {channel_map[cid]['name']}",
            )
            sender = st.text_input("Sender / Source", placeholder="e.g., Client, Rahul, System")
            title = st.text_input("Subject / Summary", placeholder="e.g., Meeting at 4 PM")
            body = st.text_area("Message / Details", placeholder="Write the update or note...")
            add_btn = st.form_submit_button("Add to Last-24h Feed", use_container_width=True)

            if add_btn:
                if sender.strip() and title.strip() and body.strip():
                    add_feed_item(
                        user_id=user["id"],
                        channel=target_channel,
                        sender=sender,
                        title=title,
                        body=body,
                        created_at=datetime.now(timezone.utc),
                    )
                    st.success("Added to feed!")
                    st.rerun()
                else:
                    st.warning("Please fill in sender, title, and message details.")

        st.divider()
        st.subheader("🧪 Sample 24h Data")
        st.caption("Populate realistic last-24h items across WhatsApp, Email, Calls, and Tasks to test right away.")
        if st.button("Load Sample 24h Items", use_container_width=True):
            for sample in get_sample_24h_items():
                add_feed_item(
                    user_id=user["id"],
                    channel=sample["channel"],
                    sender=sample["sender"],
                    title=sample["title"],
                    body=sample["body"],
                    created_at=sample["created_at"],
                )
            st.success("Sample 24h items loaded!")
            st.rerun()


if st.session_state.user:
    render_dashboard()
else:
    render_auth_screen()
