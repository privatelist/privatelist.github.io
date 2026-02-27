#!/usr/bin/env python3
"""
PLC Daily Intelligence Report
Fetches Gmail, Google Calendar, Slack → formats → sends via Telegram image + email
"""

import os
import json
import smtplib
import tempfile
import requests
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

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

SMTP_HOST       = os.environ["NAMESECURE_SMTP_HOST"]
SMTP_PASS       = os.environ["NAMESECURE_SUPPORT_PASS"]
REPORT_FROM     = os.environ["REPORT_FROM_EMAIL"]
REPORT_TO       = os.environ["REPORT_TO_EMAIL"]

PHOENIX_TZ_OFFSET = timedelta(hours=-7)  # America/Phoenix (no DST)


# ─── OAuth helpers ─────────────────────────────────────────────────────────────
def get_google_access_token(client_id, client_secret, refresh_token):
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={"client_id": client_id, "client_secret": client_secret,
              "refresh_token": refresh_token, "grant_type": "refresh_token"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


# ─── Gmail ────────────────────────────────────────────────────────────────────
def fetch_gmail(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    cutoff  = int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp())
    list_r  = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers=headers, params={"q": f"after:{cutoff}", "maxResults": 15}, timeout=15)
    list_r.raise_for_status()
    emails = []
    for msg in list_r.json().get("messages", [])[:15]:
        detail = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
            headers=headers,
            params={"format": "metadata", "metadataHeaders": ["From", "Subject"]},
            timeout=15)
        if detail.status_code != 200:
            continue
        d    = detail.json()
        hdrs = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
        emails.append({"subject": hdrs.get("Subject", "(no subject)"),
                       "sender":  hdrs.get("From", "unknown"),
                       "snippet": d.get("snippet", "")})
    return emails


# ─── Google Calendar ──────────────────────────────────────────────────────────
def fetch_calendar(access_token):
    headers   = {"Authorization": f"Bearer {access_token}"}
    now_utc   = datetime.now(timezone.utc)
    phoenix   = now_utc + PHOENIX_TZ_OFFSET
    day_start = (phoenix.replace(hour=0,  minute=0,  second=0,  microsecond=0) - PHOENIX_TZ_OFFSET)
    day_end   = (phoenix.replace(hour=23, minute=59, second=59, microsecond=0) - PHOENIX_TZ_OFFSET)
    r = requests.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        headers=headers,
        params={"timeMin": day_start.isoformat().replace("+00:00", "Z"),
                "timeMax": day_end.isoformat().replace("+00:00", "Z"),
                "singleEvents": "true", "orderBy": "startTime", "maxResults": 20},
        timeout=15)
    r.raise_for_status()
    events = []
    for item in r.json().get("items", []):
        start    = item.get("start", {})
        start_dt = start.get("dateTime") or start.get("date", "")
        if "T" in start_dt:
            dt       = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
            time_str = (dt + PHOENIX_TZ_OFFSET).strftime("%I:%M %p").lstrip("0")
        else:
            time_str = "All Day"
        events.append({"time": time_str, "summary": item.get("summary", "(no title)")})
    return events


# ─── Slack ────────────────────────────────────────────────────────────────────
SLACK_CHANNELS_OF_INTEREST = ["general", "engineering", "alerts", "random"]

def fetch_slack(bot_token):
    headers = {"Authorization": f"Bearer {bot_token}"}
    cutoff  = (datetime.now(timezone.utc) - timedelta(hours=24)).timestamp()
    ch_r    = requests.get("https://slack.com/api/conversations.list",
                           headers=headers,
                           params={"exclude_archived": "true",
                                   "types": "public_channel,private_channel", "limit": 200},
                           timeout=15)
    ch_r.raise_for_status()
    channels     = {c["name"]: c["id"] for c in ch_r.json().get("channels", [])}
    target_names = [n for n in SLACK_CHANNELS_OF_INTEREST if n in channels]
    if not target_names:
        target_names = list(channels.keys())[:4]
    results = []
    for name in target_names[:4]:
        ch_id  = channels.get(name)
        hist_r = requests.get("https://slack.com/api/conversations.history",
                              headers=headers,
                              params={"channel": ch_id, "oldest": str(cutoff), "limit": 5},
                              timeout=15)
        if not hist_r.ok:
            continue
        for m in hist_r.json().get("messages", [])[:3]:
            text = m.get("text", "").strip()
            if text:
                results.append({"channel": f"#{name}", "text": text[:120]})
    return results


# ─── HTML report builder ──────────────────────────────────────────────────────
def build_report_html(emails, events, slack_msgs, phoenix_now):
    date_str = phoenix_now.strftime("%b %-d, %Y")
    time_str = phoenix_now.strftime("%-I:%M %p")

    def li(items):
        if not items:
            return '<li><span style="color:#C47D3A;font-weight:bold;margin-right:8px;">&#8212;</span>Nothing to report.</li>'
        return "".join(f'<li><span style="color:#C47D3A;font-weight:bold;margin-right:8px;">&#8212;</span>{i}</li>' for i in items)

    cal_items   = [f"{e['time']} \u2014 {e['summary']}" for e in events] or ["No events today."]
    email_items = []
    for em in emails[:8]:
        sender = em["sender"].split("<")[0].strip().strip('"')[:35]
        email_items.append(f"{em['subject'][:65]} \u2014 <em>{sender}</em>")
    if not email_items:
        email_items = ["No new email."]
    slack_items = [f"{sm['channel']}: {sm['text'][:80]}" for sm in slack_msgs[:5]] or ["No Slack activity."]

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
       background:#fff; width:500px; }}
.header {{ background:#1E3A5F; padding:18px 24px; color:#fff; }}
.header h1 {{ font-size:18px; font-weight:700; margin-bottom:4px; }}
.header .date {{ font-size:12px; color:#AAC; }}
.content {{ padding:20px 24px; }}
.section {{ margin-bottom:18px; }}
.section h2 {{ font-size:13px; font-weight:700; color:#1E3A5F;
               margin-bottom:8px; letter-spacing:.5px; }}
.section ul {{ list-style:none; }}
.section li {{ font-size:13px; color:#2C2C2C;
               padding:3px 0 3px 16px; position:relative; }}
.section li:before {{ content:"\00b7"; position:absolute; left:0;
                      color:#C47D3A; font-weight:bold; font-size:18px; }}
.footer {{ padding:14px 24px; font-size:11px; color:#5A7E7E;
           border-top:1px solid #eee; }}
</style></head><body>
<div class="header">
  <h1>PRIVATE LIST CONSULTING</h1>
  <div class="date">Daily Intelligence Report &middot; {date_str} &middot; {time_str} Phoenix</div>
</div>
<div class="content">
  <div class="section"><h2>CALENDAR TODAY</h2><ul>{li(cal_items)}</ul></div>
  <div class="section"><h2>EMAIL</h2><ul>{li(email_items)}</ul></div>
  <div class="section"><h2>SLACK</h2><ul>{li(slack_items)}</ul></div>
</div>
<div class="footer">Private List Consulting \u2014 Delivered by jFISH</div>
</body></html>"""


# ─── Telegram image delivery ──────────────────────────────────────────────────
def send_telegram_image(html):
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as tmp:
        html_path = os.path.join(tmp, "report.html")
        img_path  = os.path.join(tmp, "report.png")
        with open(html_path, "w") as f:
            f.write(html)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page    = browser.new_page(viewport={"width": 500, "height": 900})
            page.goto(f"file://{html_path}")
            page.wait_for_timeout(500)
            page.locator("body").screenshot(path=img_path)
            browser.close()
        with open(img_path, "rb") as img:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                data={"chat_id": TELEGRAM_CHAT_ID},
                files={"photo": img},
                timeout=30).raise_for_status()


# ─── Email delivery ───────────────────────────────────────────────────────────
def build_email_html(emails, events, slack_msgs, phoenix_now):
    date_str = phoenix_now.strftime("%A, %B %-d, %Y")

    def rows(items, color="#C47D3A"):
        if not items:
            return "<tr><td style='padding:4px 0;color:#888;'>Nothing to report.</td></tr>"
        return "".join(
            f"<tr><td style='padding:4px 8px;color:{color};'>&#9679;</td>"
            f"<td style='padding:4px 0;font-size:13px;'>{i}</td></tr>"
            for i in items)

    cal_items   = [f"{e['time']} \u2014 {e['summary']}" for e in events]
    email_items = []
    for em in emails[:8]:
        sender = em["sender"].split("<")[0].strip().strip('"')[:35]
        email_items.append(f"<strong>{em['subject'][:65]}</strong> &mdash; <span style='color:#666'>{sender}</span>")
    slack_items = [f"<strong>{sm['channel']}</strong>: {sm['text'][:80]}" for sm in slack_msgs[:5]]

    return f"""<!DOCTYPE html><html><body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif;">
<table width="550" cellpadding="0" cellspacing="0" style="margin:20px 0;background:#fff;border-radius:6px;overflow:hidden;">
  <tr><td style="background:#1E3A5F;padding:24px 32px;">
    <h1 style="margin:0;color:#fff;font-size:20px;">Private List Consulting</h1>
    <p style="margin:4px 0 0;color:#C47D3A;font-size:13px;">Daily Intelligence Report &mdash; {date_str}</p>
  </td></tr>
  <tr><td style="padding:24px 32px;">
    <h2 style="color:#1E3A5F;font-size:15px;border-bottom:2px solid #C47D3A;padding-bottom:6px;">&#128197; Calendar Today</h2>
    <table width="100%">{rows(cal_items)}</table>
    <h2 style="color:#1E3A5F;font-size:15px;border-bottom:2px solid #C47D3A;padding-bottom:6px;margin-top:20px;">&#128140; Recent Email</h2>
    <table width="100%">{rows(email_items)}</table>
    <h2 style="color:#1E3A5F;font-size:15px;border-bottom:2px solid #C47D3A;padding-bottom:6px;margin-top:20px;">&#128172; Slack</h2>
    <table width="100%">{rows(slack_items)}</table>
  </td></tr>
  <tr><td style="background:#f9f9f9;padding:12px 32px;text-align:center;color:#999;font-size:11px;">
    Delivered by jFISH &middot; Private List Consulting
  </td></tr>
</table></body></html>"""


def send_email(html_body, date_str):
    msg            = MIMEMultipart("alternative")
    msg["Subject"] = f"PLC Daily Intelligence Report \u2014 {date_str}"
    msg["From"]    = REPORT_FROM
    msg["To"]      = REPORT_TO
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(SMTP_HOST, 587) as s:
        s.ehlo()
        s.starttls()
        s.login(REPORT_FROM, SMTP_PASS)
        s.sendmail(REPORT_FROM, [REPORT_TO], msg.as_string())


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    phoenix_now = datetime.now(timezone.utc) + PHOENIX_TZ_OFFSET

    print("Fetching Gmail...")
    gmail_token = get_google_access_token(GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN)
    emails = fetch_gmail(gmail_token)
    print(f"  {len(emails)} emails.")

    print("Fetching Google Calendar...")
    gcal_token = get_google_access_token(GCAL_CLIENT_ID, GCAL_CLIENT_SECRET, GCAL_REFRESH_TOKEN)
    events = fetch_calendar(gcal_token)
    print(f"  {len(events)} events.")

    print("Fetching Slack...")
    try:
        slack_msgs = fetch_slack(SLACK_BOT_TOKEN)
        print(f"  {len(slack_msgs)} Slack messages.")
    except Exception as e:
        print(f"  Slack fetch failed (non-fatal): {e}")
        slack_msgs = []

    print("Sending Telegram image...")
    report_html = build_report_html(emails, events, slack_msgs, phoenix_now)
    send_telegram_image(report_html)
    print("  Telegram sent.")

    print("Sending email...")
    date_str   = phoenix_now.strftime("%A, %B %-d, %Y")
    email_html = build_email_html(emails, events, slack_msgs, phoenix_now)
    send_email(email_html, date_str)
    print("  Email sent.")

    print("Done.")


if __name__ == "__main__":
    main()
