# YouTube Video Review Workflow

## THE RULE
**NEVER load a YouTube transcript into the main session context.**
Always spawn a sub-agent. Always. No exceptions.

If the sub-agent fails, fix the sub-agent — do not fall back to loading the transcript in main session.

---

## Why
- Full transcripts = 10k-20k+ tokens dumped into main context
- That bloat carries forward for the rest of the session, making every subsequent turn more expensive
- Sub-agent isolates the cost, throws away the transcript after summarizing
- Main session only receives the summary (~300-500 tokens)
- Cost with sub-agent: ~$0.05-0.08 | Cost without: ~$0.58+

---

## The Workflow

1. Joseph sends a YouTube URL
2. Elle spawns a sub-agent (Haiku) with the URL and task
3. Sub-agent runs `yt_transcript.py`, reads transcript, returns structured summary
4. Sub-agent session ends — transcript is gone
5. Main session receives summary only

---

## The sessions_spawn Call

```python
sessions_spawn(
    task=f"""Fetch and summarize this YouTube video: {url}

Run this command and read the full output:
  python3 /data/.openclaw/workspace/scripts/yt_transcript.py {url}

Then return a structured summary with:
- 1-paragraph overview of what the video is about
- Key topics covered with approximate timestamps
- Actionable takeaways or decisions relevant to PrivateList
- The transcript file path from the TRANSCRIPT_SAVED line in the output

IMPORTANT: Return the summary only. Do NOT include the full transcript text in your response.""",
    model="anthropic/claude-haiku-4-5",
    mode="run",
    cleanup="keep"
)
```

---

## Script Location
`/data/.openclaw/workspace/scripts/yt_transcript.py`

Handles VPS IP blocking via Supadata.ai (external fetch).
Fallbacks: youtube-transcript-api → yt-dlp
Saves transcript to: `/data/.openclaw/workspace/transcripts/`

---

## If the Script Fails
1. Check Supadata key: `/data/.openclaw/secrets/supadata.key`
2. Check Supadata free tier limit (100 req/month)
3. Try direct curl: `curl -s "https://api.supadata.ai/v1/youtube/transcript?url=<URL>&text=true" -H "x-api-key: $(cat /data/.openclaw/secrets/supadata.key)"`
4. If all methods fail — tell Joseph, do NOT dump raw content into main session

---

## Distribution
This file lives at: `memory/yt-workflow.md`
All three agents should have identical copies.
Last updated: 2026-02-27
