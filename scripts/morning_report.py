#!/usr/bin/env python3
"""
PLC Daily Intelligence Report
Fetches Gmail, Google Calendar, Slack — runs AI analysis via Gemini —
formats — sends via Telegram image + email

v3 — AI Layer: Gemini 2.5 Pro generates executive summary, action items,
     and priority ranking from raw data. AI layer is resilient — if Gemini
     fails, the report still delivers with raw data only.

v2 — Resilient: each data source is independent. If one fails, the report
     still generates with whatever data IS available. Failures are shown
     inline so the reader knows what's missing and why.
"""

import os
import json
import smtplib
import tempfile
import traceback
import requests
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ─── Config ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

GMAIL_CLIENT_ID     = os.environ.get("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET")
GMAIL_REFRESH_TOKEN = os.environ.get("GMAIL_REFRESH_TOKEN")

GCAL_CLIENT_ID     = os.environ.get("GCAL_CLIENT_ID")
GCAL_CLIENT_SECRET = os.environ.get("GCAL_CLIENT_SECRET")
GCAL_REFRESH_TOKEN = os.environ.get("GCAL_REFRESH_TOKEN")

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL   = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")

SMTP_HOST   = os.environ.get("NAMESECURE_SMTP_HOST")
SMTP_PASS   = os.environ.get("NAMESECURE_SUPPORT_PASS")
REPORT_FROM = os.environ.get("REPORT_FROM_EMAIL")
REPORT_TO   = os.environ.get("REPORT_TO_EMAIL")

PHOENIX_TZ_OFFSET = timedelta(hours=-7)  # America/Phoenix (no DST)
PHOENIX_TZ = timezone(timedelta(hours=-7))

# ─── Preflight ───────────────────────────────────────────────────────────────
def required_envs_preflight():
    """Check for critical delivery secrets only. Data-source secrets are
    checked at fetch time so a missing source doesn't block the whole report."""
    critical = [
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
        "NAMESECURE_SMTP_HOST", "NAMESECURE_SUPPORT_PASS",
        "REPORT_FROM_EMAIL", "REPORT_TO_EMAIL",
    ]
    missing = [k for k in critical if not os.environ.get(k)]
    return missing


# ─── OAuth helpers ───────────────────────────────────────────────────────────
def get_google_access_token(client_id, client_secret, refresh_token):
    """Exchange a refresh token for an access token. Raises on failure."""
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    if r.status_code != 200:
        # Include the actual Google error for debugging
        try:
            detail = r.json()
        except Exception:
            detail = r.text[:200]
        raise RuntimeError(
            f"Google OAuth token refresh failed ({r.status_code}): {detail}"
        )
    return r.json()["access_token"]


# ─── Gmail ───────────────────────────────────────────────────────────────────
def fetch_gmail(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    cutoff = int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp())
    list_r = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers=headers,
        params={"q": f"after:{cutoff}", "maxResults": 15},
        timeout=15,
    )
    list_r.raise_for_status()
    emails = []
    for msg in list_r.json().get("messages", [])[:15]:
        detail = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
            headers=headers,
            params={"format": "metadata", "metadataHeaders": ["From", "Subject"]},
            timeout=15,
        )
        if detail.status_code != 200:
            continue
        d = detail.json()
        hdrs = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
        emails.append({
            "subject": hdrs.get("Subject", "(no subject)"),
            "sender": hdrs.get("From", "unknown"),
            "snippet": d.get("snippet", ""),
        })
    return emails


# ─── Google Calendar ─────────────────────────────────────────────────────────
def fetch_calendar(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    now_utc = datetime.now(timezone.utc)
    phoenix = now_utc + PHOENIX_TZ_OFFSET
    day_start = phoenix.replace(hour=0, minute=0, second=0, microsecond=0) - PHOENIX_TZ_OFFSET
    day_end = phoenix.replace(hour=23, minute=59, second=59, microsecond=0) - PHOENIX_TZ_OFFSET
    r = requests.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        headers=headers,
        params={
            "timeMin": day_start.isoformat().replace("+00:00", "Z"),
            "timeMax": day_end.isoformat().replace("+00:00", "Z"),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 20,
        },
        timeout=15,
    )
    r.raise_for_status()
    events = []
    for item in r.json().get("items", []):
        start = item.get("start", {})
        start_dt = start.get("dateTime") or start.get("date", "")
        if "T" in start_dt:
            dt = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
            time_str = dt.astimezone(PHOENIX_TZ).strftime("%I:%M %p").lstrip("0")
        else:
            time_str = "All Day"
        events.append({"time": time_str, "summary": item.get("summary", "(no title)")})
    return events


# ─── Slack ───────────────────────────────────────────────────────────────────
SLACK_CHANNELS_OF_INTEREST = ["general", "engineering", "alerts", "random"]

def fetch_slack(bot_token):
    headers = {"Authorization": f"Bearer {bot_token}"}
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).timestamp()
    ch_r = requests.get(
        "https://slack.com/api/conversations.list",
        headers=headers,
        params={
            "exclude_archived": "true",
            "types": "public_channel,private_channel",
            "limit": 200,
        },
        timeout=15,
    )
    ch_r.raise_for_status()
    channels = {c["name"]: c["id"] for c in ch_r.json().get("channels", [])}
    target_names = [n for n in SLACK_CHANNELS_OF_INTEREST if n in channels]
    if not target_names:
        target_names = list(channels.keys())[:4]
    results = []
    for name in target_names[:4]:
        ch_id = channels.get(name)
        hist_r = requests.get(
            "https://slack.com/api/conversations.history",
            headers=headers,
            params={"channel": ch_id, "oldest": str(cutoff), "limit": 5},
            timeout=15,
        )
        if not hist_r.ok:
            continue
        for m in hist_r.json().get("messages", [])[:3]:
            text = m.get("text", "").strip()
            if text:
                results.append({"channel": f"#{name}", "text": text[:120]})
    return results


# ─── AI Summary (Gemini 2.5 Pro) ────────────────────────────────────────────

def build_ai_prompt(emails, events, slack_msgs, errors, phoenix_now):
    """Build a structured prompt from raw data for Gemini to analyze."""
    date_str = phoenix_now.strftime("%A, %B %d, %Y")

    # Calendar section
    if "calendar" in errors:
        cal_block = "CALENDAR: [unavailable — source error]"
    elif not events:
        cal_block = "CALENDAR: No events today."
    else:
        cal_lines = [f"  - {e['time']}: {e['summary']}" for e in events]
        cal_block = "CALENDAR TODAY:\n" + "\n".join(cal_lines)

    # Email section
    if "gmail" in errors:
        email_block = "EMAIL: [unavailable — source error]"
    elif not emails:
        email_block = "EMAIL: No new emails in last 24 hours."
    else:
        email_lines = []
        for em in emails[:15]:
            sender = em["sender"].split("<")[0].strip().strip('"')[:40]
            email_lines.append(f"  - From: {sender} | Subject: {em['subject'][:80]} | Preview: {em['snippet'][:100]}")
        email_block = "EMAIL (last 24 hours):\n" + "\n".join(email_lines)

    # Slack section
    if "slack" in errors:
        slack_block = "SLACK: [unavailable — source error]"
    elif not slack_msgs:
        slack_block = "SLACK: No activity in last 24 hours."
    else:
        slack_lines = [f"  - {sm['channel']}: {sm['text'][:120]}" for sm in slack_msgs]
        slack_block = "SLACK ACTIVITY:\n" + "\n".join(slack_lines)

    prompt = f"""You are an executive briefing analyst for a small AI consulting agency (Private List Consulting).
Today is {date_str}. Analyze the following raw data and produce a morning intelligence briefing.

--- RAW DATA ---
{cal_block}

{email_block}

{slack_block}
--- END RAW DATA ---

Produce EXACTLY this format (no markdown, no extra headers, plain text):

EXECUTIVE SUMMARY:
[2-3 sentences: What does today look like? What deserves attention? Any scheduling conflicts or time-sensitive items?]

ACTION ITEMS:
- [Specific action extracted from the data — who/what/when]
- [Another action item]
- [Up to 5 items max. Only include real, actionable items from the data. If nothing is actionable, say "No immediate action items."]

PRIORITIES:
1. [Highest priority item for today with brief reason]
2. [Second priority]
3. [Third priority, if applicable]

Rules:
- Be concise and direct. No filler.
- If a data source was unavailable, note it briefly but don't dwell on it.
- Extract names, times, and specifics — don't be vague.
- If emails look like newsletters or automated notifications, deprioritize them.
- Focus on things that require Joseph's attention or response."""

    return prompt


def call_gemini(prompt):
    """Call Gemini API and return the generated text. Raises on failure."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 800,
        },
    }
    r = requests.post(
        url,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=30,
    )
    if r.status_code != 200:
        try:
            detail = r.json()
        except Exception:
            detail = r.text[:300]
        raise RuntimeError(f"Gemini API error ({r.status_code}): {detail}")

    data = r.json()
    # Extract text from Gemini response
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError(f"Gemini returned empty parts: {data}")
    return parts[0].get("text", "").strip()


def safe_fetch_ai_summary(emails, events, slack_msgs, errors, phoenix_now):
    """Generate AI summary. Returns (summary_text, error_or_None).
    Follows the same resilient pattern as data source fetchers."""
    if not GEMINI_API_KEY:
        return None, "Gemini API key not configured"
    try:
        prompt = build_ai_prompt(emails, events, slack_msgs, errors, phoenix_now)
        summary = call_gemini(prompt)
        return summary, None
    except Exception as e:
        return None, f"AI summary failed: {e}"


def parse_ai_summary(raw_summary):
    """Parse the raw AI text into structured sections.
    Returns dict with keys: executive_summary, action_items, priorities."""
    result = {"executive_summary": "", "action_items": [], "priorities": []}
    if not raw_summary:
        return result

    current_section = None
    lines = raw_summary.strip().split("\n")

    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()

        if upper.startswith("EXECUTIVE SUMMARY"):
            current_section = "executive_summary"
            continue
        elif upper.startswith("ACTION ITEMS") or upper.startswith("ACTION ITEM"):
            current_section = "action_items"
            continue
        elif upper.startswith("PRIORITIES") or upper.startswith("PRIORITY"):
            current_section = "priorities"
            continue

        if not stripped:
            continue

        if current_section == "executive_summary":
            result["executive_summary"] += (" " + stripped) if result["executive_summary"] else stripped
        elif current_section == "action_items":
            item = stripped.lstrip("-•*0123456789.) ").strip()
            if item:
                result["action_items"].append(item)
        elif current_section == "priorities":
            item = stripped.lstrip("-•*0123456789.) ").strip()
            if item:
                result["priorities"].append(item)

    return result


# ─── Safe fetch wrappers ─────────────────────────────────────────────────────
# Each returns (data_list, error_string_or_None)

def safe_fetch_gmail():
    """Attempt Gmail fetch. Returns (emails, error)."""
    if not all([GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN]):
        return [], "Gmail secrets not configured"
    try:
        token = get_google_access_token(GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN)
        emails = fetch_gmail(token)
        return emails, None
    except Exception as e:
        return [], f"Gmail failed: {e}"


def safe_fetch_calendar():
    """Attempt Calendar fetch. Returns (events, error)."""
    if not all([GCAL_CLIENT_ID, GCAL_CLIENT_SECRET, GCAL_REFRESH_TOKEN]):
        return [], "Calendar secrets not configured"
    try:
        token = get_google_access_token(GCAL_CLIENT_ID, GCAL_CLIENT_SECRET, GCAL_REFRESH_TOKEN)
        events = fetch_calendar(token)
        return events, None
    except Exception as e:
        return [], f"Calendar failed: {e}"


def safe_fetch_slack():
    """Attempt Slack fetch. Returns (messages, error)."""
    if not SLACK_BOT_TOKEN:
        return [], "Slack token not configured"
    try:
        msgs = fetch_slack(SLACK_BOT_TOKEN)
        return msgs, None
    except Exception as e:
        return [], f"Slack failed: {e}"


# ─── HTML report builder (Telegram image) ───────────────────────────────────
def build_report_html(emails, events, slack_msgs, errors, phoenix_now, ai_summary=None):
    date_str = phoenix_now.strftime("%b %-d, %Y")
    time_str = phoenix_now.strftime("%-I:%M %p")

    def li(items):
        if not items:
            return '<li><span style="color:#C47D3A;font-weight:bold;margin-right:8px;">&#8212;</span>Nothing to report.</li>'
        return "".join(
            f'<li><span style="color:#C47D3A;font-weight:bold;margin-right:8px;">&#8212;</span>{i}</li>'
            for i in items
        )

    def error_banner(source_name, err):
        """Inline error notice for a failed data source."""
        return (
            f'<li style="color:#C44; font-size:12px; font-style:italic;">'
            f'⚠️ {source_name} unavailable — check credentials</li>'
        )

    cal_items = [f"{e['time']} — {e['summary']}" for e in events] or ["No events today."]
    email_items = []
    for em in emails[:8]:
        sender = em["sender"].split("<")[0].strip().strip('"')[:35]
        email_items.append(f"{em['subject'][:65]} — <em>{sender}</em>")
    if not email_items:
        email_items = ["No new email."]
    slack_items = [f"{sm['channel']}: {sm['text'][:80]}" for sm in slack_msgs[:5]] or ["No Slack activity."]

    # Build error notices for each failed source
    cal_error = error_banner("Calendar", errors.get("calendar")) if "calendar" in errors else ""
    email_error = error_banner("Gmail", errors.get("gmail")) if "gmail" in errors else ""
    slack_error = error_banner("Slack", errors.get("slack")) if "slack" in errors else ""

    # If a source failed, replace its items with just the error notice
    cal_list = cal_error if "calendar" in errors else li(cal_items)
    email_list = email_error if "gmail" in errors else li(email_items)
    slack_list = slack_error if "slack" in errors else li(slack_items)

    # Build AI briefing section
    ai_section = ""
    if ai_summary:
        parsed = parse_ai_summary(ai_summary)
        exec_html = parsed["executive_summary"] or "No summary generated."

        actions_html = ""
        if parsed["action_items"]:
            actions_html = '<div class="sub-header">ACTION ITEMS</div><ul>'
            for item in parsed["action_items"][:5]:
                actions_html += f'<li><span style="color:#C47D3A;margin-right:6px;">&#9656;</span>{item}</li>'
            actions_html += "</ul>"

        priorities_html = ""
        if parsed["priorities"]:
            priorities_html = '<div class="sub-header">PRIORITIES</div><ul>'
            for i, item in enumerate(parsed["priorities"][:3], 1):
                priorities_html += f'<li><span style="color:#C47D3A;font-weight:bold;margin-right:6px;">{i}.</span>{item}</li>'
            priorities_html += "</ul>"

        ai_section = f"""<div class="ai-briefing">
    <h2>AI EXECUTIVE BRIEFING</h2>
    <div class="summary">{exec_html}</div>
    {actions_html}
    {priorities_html}
  </div>"""
    else:
        ai_section = '<div class="ai-unavailable">AI briefing unavailable this run.</div>'

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Lucida Grande','Lucida Sans Unicode','Lucida Sans',Arial,sans-serif;
       background:#fff; width:500px; }}
.header {{ background:#1E3A5F; padding:18px 24px; color:#fff; }}
.header h1 {{ font-size:18px; font-weight:700; margin-bottom:4px; }}
.header .date {{ font-size:12px; color:#AAC; }}
.status-bar {{ background:#F0F4F8; padding:8px 24px; font-size:11px; color:#666; border-bottom:1px solid #E0E4E8; }}
.status-bar .ok {{ color:#2A7F2A; }}
.status-bar .err {{ color:#C44; }}
.content {{ padding:20px 24px; }}
.section {{ margin-bottom:18px; }}
.section h2 {{ font-size:13px; font-weight:700; color:#1E3A5F; margin-bottom:8px; letter-spacing:.5px; }}
.section ul {{ list-style:none; }}
.section li {{ font-size:13px; color:#2C2C2C; padding:3px 0; }}
.ai-briefing {{ background:#F8F6F0; border-left:3px solid #C47D3A; padding:14px 18px; margin-bottom:18px; }}
.ai-briefing h2 {{ font-size:13px; font-weight:700; color:#C47D3A; margin-bottom:8px; letter-spacing:.5px; }}
.ai-briefing .summary {{ font-size:12px; color:#2C2C2C; line-height:1.5; margin-bottom:10px; }}
.ai-briefing .sub-header {{ font-size:11px; font-weight:700; color:#1E3A5F; margin:8px 0 4px; }}
.ai-briefing li {{ font-size:12px; color:#2C2C2C; padding:2px 0; }}
.ai-unavailable {{ font-size:11px; color:#999; font-style:italic; padding:8px 18px; margin-bottom:12px; }}
.footer {{ padding:14px 24px; font-size:11px; color:#5A7E7E; border-top:1px solid #eee; }}
</style></head><body>
<div class="header">
  <h1>PRIVATE LIST CONSULTING</h1>
  <div class="date">Daily Intelligence Report &middot; {date_str} &middot; {time_str} Phoenix</div>
</div>
<div class="status-bar">
  Sources: {'<span class="ok">Gmail ✓</span>' if 'gmail' not in errors else '<span class="err">Gmail ✗</span>'}
  &nbsp;|&nbsp; {'<span class="ok">Calendar ✓</span>' if 'calendar' not in errors else '<span class="err">Calendar ✗</span>'}
  &nbsp;|&nbsp; {'<span class="ok">Slack ✓</span>' if 'slack' not in errors else '<span class="err">Slack ✗</span>'}
  &nbsp;|&nbsp; {'<span class="ok">AI ✓</span>' if ai_summary else '<span class="err">AI ✗</span>'}
</div>
<div class="content">
  {ai_section}
  <div class="section">
    <h2>CALENDAR TODAY</h2>
    <ul>{cal_list}</ul>
  </div>
  <div class="section">
    <h2>EMAIL</h2>
    <ul>{email_list}</ul>
  </div>
  <div class="section">
    <h2>SLACK</h2>
    <ul>{slack_list}</ul>
  </div>
</div>
<div class="footer">Private List Consulting — Delivered by jFISH</div>
</body></html>"""


# ─── Telegram image delivery ────────────────────────────────────────────────
def send_telegram_image(html):
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmp:
        html_path = os.path.join(tmp, "report.html")
        img_path  = os.path.join(tmp, "report.png")
        with open(html_path, "w") as f:
            f.write(html)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 500, "height": 900})
            page.goto(f"file://{html_path}")
            page.wait_for_timeout(500)
            page.locator("body").screenshot(path=img_path)
            browser.close()
        with open(img_path, "rb") as img:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                data={"chat_id": TELEGRAM_CHAT_ID},
                files={"photo": img},
                timeout=30,
            ).raise_for_status()


# ─── Email delivery ─────────────────────────────────────────────────────────
def build_email_html(emails, events, slack_msgs, errors, phoenix_now, ai_summary=None):
    date_str = phoenix_now.strftime("%A, %B %-d, %Y")

    def rows(items, color="#C47D3A"):
        if not items:
            return "<tr><td style='padding:4px 0;color:#888;'>Nothing to report.</td></tr>"
        return "".join(
            f"<tr><td style='padding:4px 8px;color:{color};'>&#9679;</td>"
            f"<td style='padding:4px 0;font-size:13px;'>{i}</td></tr>"
            for i in items
        )

    def error_row(source_name):
        return (
            f"<tr><td colspan='2' style='padding:4px 0;color:#C44;font-size:12px;'>"
            f"⚠️ {source_name} unavailable — check credentials</td></tr>"
        )

    cal_items = [f"{e['time']} — {e['summary']}" for e in events]
    email_items = []
    for em in emails[:8]:
        sender = em["sender"].split("<")[0].strip().strip('"')[:35]
        email_items.append(
            f"<strong>{em['subject'][:65]}</strong> &mdash; <span style='color:#666'>{sender}</span>"
        )
    slack_items = [
        f"<strong>{sm['channel']}</strong>: {sm['text'][:80]}" for sm in slack_msgs[:5]
    ]

    cal_rows = error_row("Calendar") if "calendar" in errors else rows(cal_items)
    email_rows = error_row("Gmail") if "gmail" in errors else rows(email_items)
    slack_rows = error_row("Slack") if "slack" in errors else rows(slack_items)

    # Status summary line
    source_status = []
    for name, key in [("Gmail", "gmail"), ("Calendar", "calendar"), ("Slack", "slack")]:
        if key in errors:
            source_status.append(f'<span style="color:#C44;">{name} ✗</span>')
        else:
            source_status.append(f'<span style="color:#2A7F2A;">{name} ✓</span>')
    # AI status
    if ai_summary:
        source_status.append('<span style="color:#2A7F2A;">AI ✓</span>')
    else:
        source_status.append('<span style="color:#C44;">AI ✗</span>')
    status_line = " &nbsp;|&nbsp; ".join(source_status)

    # AI briefing section for email
    ai_email_section = ""
    if ai_summary:
        parsed = parse_ai_summary(ai_summary)
        exec_text = parsed["executive_summary"] or "No summary generated."

        actions_rows = ""
        if parsed["action_items"]:
            actions_rows = '<tr><td colspan="2" style="padding:8px 0 4px;font-size:12px;font-weight:bold;color:#1E3A5F;">Action Items</td></tr>'
            for item in parsed["action_items"][:5]:
                actions_rows += (
                    f'<tr><td style="padding:2px 8px;color:#C47D3A;font-size:11px;">&#9656;</td>'
                    f'<td style="padding:2px 0;font-size:12px;">{item}</td></tr>'
                )

        priorities_rows = ""
        if parsed["priorities"]:
            priorities_rows = '<tr><td colspan="2" style="padding:8px 0 4px;font-size:12px;font-weight:bold;color:#1E3A5F;">Priorities</td></tr>'
            for i, item in enumerate(parsed["priorities"][:3], 1):
                priorities_rows += (
                    f'<tr><td style="padding:2px 8px;color:#C47D3A;font-weight:bold;font-size:12px;">{i}.</td>'
                    f'<td style="padding:2px 0;font-size:12px;">{item}</td></tr>'
                )

        ai_email_section = f"""<tr><td style="padding:20px 32px;background:#F8F6F0;border-left:3px solid #C47D3A;">
      <h2 style="color:#C47D3A;font-size:15px;margin:0 0 8px;">AI Executive Briefing</h2>
      <p style="font-size:13px;color:#2C2C2C;line-height:1.6;margin:0 0 10px;">{exec_text}</p>
      <table width="100%">{actions_rows}{priorities_rows}</table>
    </td></tr>"""
    else:
        ai_email_section = """<tr><td style="padding:8px 32px;font-size:11px;color:#999;font-style:italic;">
      AI briefing unavailable this run.
    </td></tr>"""

    return f"""<!DOCTYPE html><html><body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif;">
<table width="550" cellpadding="0" cellspacing="0" style="margin:20px 0;background:#fff;border-radius:6px;overflow:hidden;">
  <tr><td style="background:#1E3A5F;padding:24px 32px;">
    <h1 style="margin:0;color:#fff;font-size:20px;">Private List Consulting</h1>
    <p style="margin:4px 0 0;color:#C47D3A;font-size:13px;">Daily Intelligence Report &mdash; {date_str}</p>
  </td></tr>
  <tr><td style="padding:8px 32px;background:#F0F4F8;font-size:11px;color:#666;">
    Sources: {status_line}
  </td></tr>
  {ai_email_section}
  <tr><td style="padding:24px 32px;">
    <h2 style="color:#1E3A5F;font-size:15px;border-bottom:2px solid #C47D3A;padding-bottom:6px;">&#128197; Calendar Today</h2>
    <table width="100%">{cal_rows}</table>

    <h2 style="color:#1E3A5F;font-size:15px;border-bottom:2px solid #C47D3A;padding-bottom:6px;margin-top:20px;">&#128140; Recent Email</h2>
    <table width="100%">{email_rows}</table>

    <h2 style="color:#1E3A5F;font-size:15px;border-bottom:2px solid #C47D3A;padding-bottom:6px;margin-top:20px;">&#128172; Slack</h2>
    <table width="100%">{slack_rows}</table>
  </td></tr>
  <tr><td style="background:#f9f9f9;padding:12px 32px;text-align:center;color:#999;font-size:11px;">
    Delivered by jFISH &middot; Private List Consulting
  </td></tr>
</table></body></html>"""


def send_email(html_body, date_str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"PLC Daily Intelligence Report — {date_str}"
    msg["From"] = REPORT_FROM
    msg["To"]   = REPORT_TO
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(SMTP_HOST, 587) as s:
        s.ehlo()
        s.starttls()
        s.login(REPORT_FROM, SMTP_PASS)
        s.sendmail(REPORT_FROM, [REPORT_TO], msg.as_string())


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    phoenix_now = datetime.now(timezone.utc) + PHOENIX_TZ_OFFSET

    # Track errors per source — key = source name, value = error message
    errors = {}

    # ── Fetch each source independently ──
    print("Fetching Gmail...")
    emails, gmail_err = safe_fetch_gmail()
    if gmail_err:
        errors["gmail"] = gmail_err
        print(f"  ⚠️  {gmail_err}")
    else:
        print(f"  {len(emails)} emails.")

    print("Fetching Google Calendar...")
    events, gcal_err = safe_fetch_calendar()
    if gcal_err:
        errors["calendar"] = gcal_err
        print(f"  ⚠️  {gcal_err}")
    else:
        print(f"  {len(events)} events.")

    print("Fetching Slack...")
    slack_msgs, slack_err = safe_fetch_slack()
    if slack_err:
        errors["slack"] = slack_err
        print(f"  ⚠️  {slack_err}")
    else:
        print(f"  {len(slack_msgs)} Slack messages.")

    # ── Report summary ──
    total_sources = 3
    failed_sources = len(errors)
    print(f"\nData sources: {total_sources - failed_sources}/{total_sources} OK")
    if errors:
        print(f"Failed: {', '.join(errors.keys())}")

    # ── AI Summary ──
    print("\nGenerating AI briefing (Gemini)...")
    ai_summary, ai_err = safe_fetch_ai_summary(emails, events, slack_msgs, errors, phoenix_now)
    if ai_err:
        errors["ai"] = ai_err
        print(f"  ⚠️  {ai_err}")
    else:
        # Show a preview of the summary in logs
        preview = ai_summary[:120].replace("\n", " ") if ai_summary else ""
        print(f"  AI briefing generated ({len(ai_summary)} chars): {preview}...")

    # ── Always generate and send the report (even if partial) ──
    delivery_errors = []

    print("\nSending Telegram image...")
    try:
        report_html = build_report_html(emails, events, slack_msgs, errors, phoenix_now, ai_summary=ai_summary)
        send_telegram_image(report_html)
        print("  Telegram sent.")
    except Exception as e:
        delivery_errors.append(f"Telegram: {e}")
        print(f"  ⚠️  Telegram failed: {e}")

    print("Sending email...")
    try:
        date_str = phoenix_now.strftime("%A, %B %-d, %Y")
        email_html = build_email_html(emails, events, slack_msgs, errors, phoenix_now, ai_summary=ai_summary)
        send_email(email_html, date_str)
        print("  Email sent.")
    except Exception as e:
        delivery_errors.append(f"Email: {e}")
        print(f"  ⚠️  Email failed: {e}")

    # ── Exit code logic ──
    # Only fail (exit 1) if BOTH delivery methods failed.
    # Data source failures are reported IN the report, not via exit code.
    if len(delivery_errors) == 2:
        print("\n❌ BOTH delivery methods failed. No report was sent.")
        for de in delivery_errors:
            print(f"  - {de}")
        raise SystemExit(1)

    if delivery_errors:
        print(f"\n⚠️  Partial delivery ({delivery_errors[0]}), but report was sent via the other channel.")

    if errors:
        print(f"\n📋 Report delivered with {failed_sources} degraded source(s): {', '.join(errors.keys())}")
        print("   Fix the credentials and the next run will include all sources.")
    else:
        print("\n✅ Full report delivered successfully.")


if __name__ == "__main__":
    # Only check delivery secrets — data source secrets are handled gracefully
    miss = required_envs_preflight()
    if miss:
        print("Missing required DELIVERY secrets:", ", ".join(miss))
        print("Cannot send report without these. Please set them in GitHub Secrets.")
        raise SystemExit(2)
    main()
