# PLC Screen Share AI Onboarding

Browser-based screen share tool for AI-assisted client onboarding.

## How It Works

1. Client opens the page in Chrome
2. Clicks "Start Session"
3. Grants screen share + microphone permissions
4. AI assistant can see their screen and talk with them
5. AI guides them through setup, can take actions via OpenClaw

## Requirements

- Modern browser with WebRTC support (Chrome recommended)
- Gemini API key (get free at https://aistudio.google.com/apikey)
- OpenClaw gateway running (optional, for tool execution)

## Setup

1. Copy the config template:
   ```bash
   cp config.example.js config.js
   ```

2. Edit `config.js` with your credentials:
   - `geminiApiKey`: Your Gemini API key
   - `openClawHost`: Your OpenClaw gateway URL
   - `openClawToken`: Your gateway auth token

3. Serve the files (any static server works):
   ```bash
   # Python
   python -m http.server 8080

   # Node
   npx serve .

   # Or deploy to GitHub Pages / Netlify / etc.
   ```

4. Open `http://localhost:8080` in Chrome

## Configuration

Edit the config in `index.html` or create a separate `config.js`:

```javascript
window.ONBOARDING_CONFIG = {
    geminiApiKey: 'YOUR_GEMINI_API_KEY',
    geminiModel: 'gemini-2.0-flash-exp',
    openClawHost: 'https://your-vps.com',
    openClawPort: 18789,
    openClawToken: 'your-gateway-token',
    systemPrompt: '...'
};
```

## File Structure

```
screen-share-onboarding/
├── index.html           # Main page
├── css/
│   └── styles.css       # Styling (PLC brand)
├── js/
│   ├── main.js          # App entry point
│   ├── gemini-client.js # Gemini Live WebSocket
│   ├── audio-manager.js # Mic capture + playback
│   ├── screen-manager.js# Screen capture
│   └── openclaw-bridge.js # Tool call routing
└── README.md
```

## Technical Details

### Audio Pipeline
- Capture: 16kHz PCM mono
- Playback: 24kHz PCM mono
- Uses Web Audio API with separate contexts for capture/playback

### Video Pipeline
- Screen capture via `getDisplayMedia()`
- Frames extracted at 1fps
- Scaled to max 1280px dimension
- JPEG compressed (quality 0.7)
- Sent as base64 to Gemini

### Tool Calling
- Gemini can call the `execute` function
- Requests route to OpenClaw gateway
- Results returned to Gemini for verbal response

## Troubleshooting

**"Permission denied" for screen share**
- Use Chrome (best support)
- Must be served over HTTPS or localhost
- User must explicitly grant permission

**No audio playback**
- Check browser console for errors
- Ensure playback context is allowed (may need user interaction)

**OpenClaw calls failing**
- Verify gateway is running and accessible
- Check CORS settings on gateway
- Verify token is correct

## Deployment

For production, deploy to:
- GitHub Pages (static hosting)
- Netlify / Vercel
- Any static file server

The app is fully client-side — no backend needed (Gemini API and OpenClaw are external).

## Security Notes

- API keys are visible in client-side code
- For production, consider a thin backend proxy
- OpenClaw token grants access to your skills — keep secure
