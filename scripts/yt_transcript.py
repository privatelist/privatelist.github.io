#!/usr/bin/env python3
"""
YouTube Transcript Fetcher — PList2
Usage: python3 yt_transcript.py <youtube_url>

Priority:
  1. Supadata.ai API (cloud, handles VPS IP blocking)
  2. youtube-transcript-api (direct, may fail on VPS IPs)
  3. yt-dlp subtitle extraction (fallback)

Saves transcript to /data/.openclaw/workspace/transcripts/
Prints structured output for agent summarization.
"""

import sys
import os
import re
import json
import urllib.request
import urllib.parse
from datetime import datetime

TRANSCRIPT_DIR = "/data/.openclaw/workspace/transcripts"
SECRETS_DIR = "/data/.openclaw/secrets"
MAX_CHARS = 80000  # ~20k tokens, safe for sub-agent context

def load_secret(filename):
    path = os.path.join(SECRETS_DIR, filename)
    try:
        with open(path, 'r') as f:
            return f.read().strip()
    except:
        return None

def extract_video_id(url):
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11})(?:[&?#]|$)",
        r"youtu\.be\/([0-9A-Za-z_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def fetch_via_supadata(video_id):
    import subprocess
    api_key = load_secret("supadata.key")
    if not api_key:
        return None, "supadata key not found"
    try:
        yt_url = urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}", safe='')
        endpoint = f"https://api.supadata.ai/v1/transcript?url={yt_url}&lang=en&text=true"
        result = subprocess.run(
            ["curl", "-s", "--max-time", "30", "-H", f"x-api-key: {api_key}", endpoint],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return None, f"curl error: {result.stderr}"
        data = json.loads(result.stdout)
        # Handle error response
        if "error" in data:
            return None, f"supadata error: {data}"
        # Extract content
        content = data.get("content") or data.get("transcript") or data.get("text")
        if content:
            if isinstance(content, list):
                lines = []
                for entry in content:
                    if isinstance(entry, dict):
                        t = int(entry.get("offset", entry.get("start", 0)) / 1000)
                        mins, secs = divmod(t, 60)
                        hrs, mins = divmod(mins, 60)
                        ts = f"[{hrs}:{mins:02d}:{secs:02d}]" if hrs else f"[{mins}:{secs:02d}]"
                        lines.append(f"{ts} {entry.get('text', '')}")
                    else:
                        lines.append(str(entry))
                return "\n".join(lines), "supadata"
            return str(content), "supadata"
        return None, f"supadata empty response: {data}"
    except Exception as e:
        return None, f"supadata error: {e}"

def fetch_via_transcript_api(video_id):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id)
        lines = []
        for entry in fetched:
            t = int(entry.start)
            mins, secs = divmod(t, 60)
            hrs, mins = divmod(mins, 60)
            ts = f"[{hrs}:{mins:02d}:{secs:02d}]" if hrs else f"[{mins}:{secs:02d}]"
            lines.append(f"{ts} {entry.text}")
        return "\n".join(lines), "transcript_api"
    except Exception as e:
        return None, str(e)

def fetch_via_yt_dlp(video_id, url):
    import yt_dlp
    tmp_path = f"/tmp/yt_sub_{video_id}"
    ydl_opts = {
        'skip_download': True,
        'writeautomaticsub': True,
        'writesubtitles': True,
        'subtitlesformat': 'vtt',
        'subtitleslangs': ['en'],
        'outtmpl': tmp_path,
        'quiet': True,
        'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        for ext in ['.en.vtt', '.en-US.vtt']:
            sub_file = tmp_path + ext
            if os.path.exists(sub_file):
                with open(sub_file, 'r') as f:
                    raw = f.read()
                lines = []
                seen = set()
                for line in raw.split('\n'):
                    line = line.strip()
                    if '-->' in line or line.startswith('WEBVTT') or line.isdigit() or not line:
                        continue
                    clean = re.sub(r'<[^>]+>', '', line)
                    if clean and clean not in seen:
                        seen.add(clean)
                        lines.append(clean)
                os.remove(sub_file)
                return "\n".join(lines), "yt_dlp_subtitles"
        return None, "no_subtitles_found"
    except Exception as e:
        return None, str(e)

def get_video_title(url):
    import yt_dlp
    ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('title', 'Unknown Title'), info.get('duration', 0)
    except:
        return 'Unknown Title', 0

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 yt_transcript.py <youtube_url>")
        sys.exit(1)

    url = sys.argv[1]
    video_id = extract_video_id(url)

    if not video_id:
        print("ERROR: Could not extract video ID from URL")
        sys.exit(1)

    print(f"Video ID: {video_id}")
    print(f"Fetching title...")
    title, duration = get_video_title(url)
    mins = duration // 60 if duration else 0
    print(f"Title: {title}")
    print(f"Duration: ~{mins} minutes")
    print()

    # Method 1: Supadata.ai
    print("Trying Supadata.ai...")
    text, method = fetch_via_supadata(video_id)

    # Method 2: transcript API
    if not text:
        print(f"Supadata failed ({method}). Trying transcript API...")
        text, method = fetch_via_transcript_api(video_id)

    # Method 3: yt-dlp
    if not text:
        print(f"Transcript API failed ({method}). Trying yt-dlp subtitles...")
        text, method = fetch_via_yt_dlp(video_id, url)

    if not text:
        print(f"ERROR: All methods failed. Last error: {method}")
        print("Video may be too new, private, or have no captions available.")
        sys.exit(1)

    # Truncate if too large
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n\n[TRUNCATED — transcript exceeded size limit]"

    # Save to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = re.sub(r'[^\w\-]', '_', title)[:50]
    filename = f"{timestamp}_{video_id}_{safe_title}.txt"
    filepath = os.path.join(TRANSCRIPT_DIR, filename)

    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
    with open(filepath, 'w') as f:
        f.write(f"Title: {title}\n")
        f.write(f"URL: {url}\n")
        f.write(f"Video ID: {video_id}\n")
        f.write(f"Duration: ~{mins} minutes\n")
        f.write(f"Method: {method}\n")
        f.write(f"Retrieved: {datetime.now().isoformat()}\n")
        f.write("=" * 60 + "\n\n")
        f.write(text)

    print(f"TRANSCRIPT_SAVED: {filepath}")
    print(f"METHOD: {method}")
    print()
    print("=" * 60)
    print("TRANSCRIPT:")
    print("=" * 60)
    print(text)

if __name__ == "__main__":
    main()
