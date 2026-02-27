#!/usr/bin/env python3
"""
PLC Daily Intelligence Report
Fetches Gmail, Google Calendar, Slack → formats → sends via Telegram
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta

# ─── Config ───────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

GMAIL_CLIENT_ID     = os.environ["GMAIL_CLIENT_ID"]
GMAIL_CLIENT_SECRET = os.environ["GMAIL_CLIENT_SECRET"]
GMAIL_REFRESH_TOKEN = os.environ["GMAIL_REFRESH_TOKEN"]

GCAL_CLIENT_ID     = os.environ["GCAL_CLIENT_ID"]
GCAL_CLIENT_SECRET = os.environ["GCAL_CLIENT_SECRET"]
GCAL_REFRESH_TOKEN = os.environ["GCAL_REFRESH_TOKEN"]

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]

PHOENIX_TZ_OFFSET = timedelta(hours=-7)  # America/Phoenix (no DST)

# ─── OAuth helpers ─────────────────────────────────────────────────────────────

def get_google_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    """Exchange a refresh token for a fresh access token."""
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id":     client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type":    "refresh_token",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


# ─── Gmail ────────────────────────────────────────────────────────────────────

def fetch_gmail(access_token: str) -> list[dict]:
    """Return up to 15 messages from the last 24 hours."""
    headers = {"Authorization": f"Bearer {access_token}"}
    cutoff  = int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp())
    query   = f"after:{cutoff}"

    list_r = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers=headers,
        params={"q": query, "maxResults": 15},
        timeout=15,
    )
    list_r.raise_for_status()
    messages = list_r.json().get("messages", [])

    emails = []
    for msg in messages[:15]:
        detail_r = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
            headers=headers,
            params={"format": "metadata", "metadataHeaders": ["From", "Subject"]},
            timeout=15,
        )
        if detail_r.status_code != 200:
            continue
        d = detail_r.json()
        hdrs = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
        emails.append({
            "subject": hdrs.get("Subject", "(no subject)"),
            "sender":  hdrs.get("From", "unknown"),
            "snippet": d.get("snippet", ""),
        })

    return emails


# ─── Google Calendar ──────────────────────────────────────────────────────────

def fetch_calendar(access_token: str) -> list[dict]:
    """Return today's calendar events (Phoenix timezone)."""
    headers = {"Authorization": f"Bearer {access_token}"}
    now_utc = datetime.now(timezone.utc)
    phoenix_now = now_utc + PHOENIX_TZ_OFFSET
    day_start = phoenix_now.replace(hour=0, minute=0, second=0, microsecond=0) - PHOENIX_TZ_OFFSET
    day_end   = phoenix_now.replace(hour=23, minute=59, second=59, microsecond=0) - PHOENIX_TZ_OFFSET

    r = requests.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        headers=headers,
        params={
            "timeMin":      day_start.isoformat().replace("+00:00", "Z"),
            "timeMax":      day_end.isoformat().replace("+00:00", "Z"),
            "singleEvents": "true",
            "orderBy":      "startTime",
            "maxResults":   20,
        },
        timeout=15,
    )
    r.raise_for_status()

    events = []
    for item in r.json().get("items", []):
        start = item.get("start", {})
        start_dt = start.get("dateTime") or start.get("date", "")
        # Parse and convert to Phoenix
        if "T" in start_dt:
            dt = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
            phoenix_dt = dt + PHOENIX_TZ_OFFSET
            time_str = phoenix_dt.strftime("%I:%M %p").lstrip("0")
        else:
            time_str = "All Day"
        events.append({"time": time_str, "summary": item.get("summary", "(no title)")})

    return events


# ─── Slack ────────────────────────────────────────────────────────────────────

SLACK_CHANNELS_OF_INTEREST = [
    "general",
    "engineering",
    "alerts",
    "random",
]

def fetch_slack(bot_token: str) -> list[dict]:
    """Return recent messages from key Slack channels."""
    headers = {"Authorization": f"Bearer {bot_token}"}
    cutoff  = (datetime.now(timezone.utc) - timedelta(hours=24)).timestamp()

    # Get list of channels the bot can see
    ch_r = requests.get(
        "https://slack.com/api/conversations.list",
        headers=headers,
        params={"exclude_archived": "true", "types": "public_channel,private_channel", "limit": 200},
        timeout=15,
    )
    ch_r.raise_for_status()
    channels = {c["name"]: c["id"] for c in ch_r.json().get("channels", [])}

    results = []
    # Try our preferred channels; fall back to whatever's available
    target_names = [n for n in SLACK_CHANNELS_OF_INTEREST if n in channels]
    if not target_names:
        target_names = list(channels.keys())[:4]

    for name in target_names[:4]:
        ch_id = channels.get(name)
        if not ch_id:
            continue
        hist_r = requests.get(
            "https://slack.com/api/conversations.history",
            headers=headers,
            params={"channel": ch_id, "oldest": str(cutoff), "limit": 5},
            timeout=15,
        )
        if not hist_r.ok:
            continue
        msgs = hist_r.json().get("messages", [])
        for m in msgs[:3]:
            text = m.get("text", "").strip()
            if text:
                results.append({"channel": f"#{name}", "text": text[:120]})

    return results


# ─── Telegram sender ──────────────────────────────────────────────────────────

def send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Telegram messages max 4096 chars; truncate if needed
    if len(text) > 4000:
        text = text[:3997] + "…"
    r = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": ""},
        timeout=15,
    )
    r.raise_for_status()


# ─── Report formatter ──────────────────────────────────────────────────────────

def format_report(
    emails: list[dict],
    events: list[dict],
    slack_msgs: list[dict],
    phoenix_now: datetime,
) -> str:
    lines = []

    date_str = phoenix_now.strftime("%A, %B %-d, %Y")
    time_str = phoenix_now.strftime("%-I:%M %p")

    lines.append("╔══════════════════════════════╗")
    lines.append("║  PRIVATE LIST CONSULTING      ║")
    lines.append("║  Daily Intelligence Report    ║")
    lines.append("╚══════════════════════════════╝")
    lines.append(f"📅  {date_str}  ·  {time_str} Phoenix")
    lines.append("")

    # ── Calendar ──
    lines.append("📆  CALENDAR TODAY")
    lines.append("─" * 32)
    if events:
        for e in events:
            lines.append(f"  {e['time']} — {e['summary']}")
    else:
        lines.append("  No events scheduled today.")
    lines.append("")

    # ── Gmail ──
    lines.append("📧  RECENT EMAIL  (last 24 hrs)")
    lines.append("─" * 32)
    if emails:
        for em in emails[:10]:
            sender = em["sender"]
            # Trim long senders to display name only
            if "<" in sender:
                sender = sender.split("<")[0].strip().strip('"')
            subject = em["subject"][:60]
            lines.append(f"  · {subject}")
            lines.append(f"    from {sender}")
    else:
        lines.append("  No new emails in the last 24 hours.")
    lines.append("")

    # ── Slack ──
    lines.append("💬  SLACK  (last 24 hrs)")
    lines.append("─" * 32)
    if slack_msgs:
        for sm in slack_msgs:
            lines.append(f"  {sm['channel']}: {sm['text'][:100]}")
    else:
        lines.append("  No recent Slack activity.")
    lines.append("")

    lines.append("─" * 32)
    lines.append("🤖  Delivered by jFISH · Private List Consulting")

    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    phoenix_now = datetime.now(timezone.utc) + PHOENIX_TZ_OFFSET

    print("Fetching Gmail...")
    gmail_token = get_google_access_token(GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN)
    emails = fetch_gmail(gmail_token)
    print(f"  Got {len(emails)} emails.")

    print("Fetching Google Calendar...")
    gcal_token = get_google_access_token(GCAL_CLIENT_ID, GCAL_CLIENT_SECRET, GCAL_REFRESH_TOKEN)
    events = fetch_calendar(gcal_token)
    print(f"  Got {len(events)} events.")

    print("Fetching Slack...")
    try:
        slack_msgs = fetch_slack(SLACK_BOT_TOKEN)
        print(f"  Got {len(slack_msgs)} Slack messages.")
    except Exception as e:
        print(f"  Slack fetch failed (non-fatal): {e}")
        slack_msgs = []

    report = format_report(emails, events, slack_msgs, phoenix_now)

    print("Sending via Telegram...")
    send_telegram(report)
    print("Done ✓")


if __name__ == "__main__":
    main()
