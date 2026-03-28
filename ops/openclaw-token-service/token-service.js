/*
 * Minimal token service for privatelistconsulting.com
 * - POST /api/admin/generate-access-url  (Authorization: Bearer <SERVICE_SECRET>)
 *   Body JSON optional: { "email": "client@example.com", "name": "Client Name" }
 * - GET  /api/onboarding-token?access=<token>
 *
 * NOTE: This implementation can run in mock mode (USE_MOCK=true) for testing.
 * For production, set USE_MOCK=false and ensure GEMINI_API_KEY is present in .env.production.
 */

const http = require('http');
const https = require('https');
const crypto = require('crypto');

const PORT = process.env.PORT || 3100;
const SERVICE_SECRET = process.env.SERVICE_SECRET || process.env.OPENCLAW_SERVICE_SECRET || '';
const SITE_DOMAIN = process.env.SITE_DOMAIN || 'privatelistconsulting.com';
const SENDGRID_API_KEY = process.env.SENDGRID_API_KEY || '';
const SENDER_EMAIL = process.env.SENDER_EMAIL || 'support@privatelistconsulting.com';
const SENDER_NAME = process.env.SENDER_NAME || 'Private List Consulting';
const GEMINI_API_KEY = process.env.GEMINI_API_KEY || '';

// In-memory store for one-time access tokens
const accessTokens = new Map();

function generateAccessToken() {
  return crypto.randomBytes(16).toString('hex'); // 32 hex chars
}

function tokenFingerprint(token) {
  return crypto.createHash('sha256').update(token).digest('hex').substring(0, 8);
}

function consumeAccessToken(token) {
  const data = accessTokens.get(token);
  if (!data) return false;
  if (data.used) return false;
  data.used = true;
  return true;
}

// periodic cleanup of expired/used tokens
setInterval(() => {
  const now = Date.now();
  const expiryMs = Number(process.env.ACCESS_TOKEN_TTL_MS || 24 * 60 * 60 * 1000);
  for (const [t, d] of accessTokens.entries()) {
    if (d.used || (now - d.created) > expiryMs) accessTokens.delete(t);
  }
}, 5 * 60 * 1000);

function getClientIP(req) {
  return req.headers['x-forwarded-for'] || req.connection.remoteAddress || '-';
}

function parseAuth(req) {
  const h = req.headers['authorization'] || req.headers['Authorization'];
  if (!h) return null;
  const parts = h.split(' ');
  if (parts.length !== 2) return null;
  return parts[1];
}

// Create ephemeral token via Google GenAI Live API
function createEphemeralToken() {
  return new Promise((resolve, reject) => {
    // Mock mode
    if (process.env.USE_MOCK === 'true') {
      const name = `auth_tokens/mock-${crypto.randomBytes(8).toString('hex')}`;
      const expires = new Date(Date.now() + 60 * 60 * 1000).toISOString();
      return resolve({ name, expireTime: expires });
    }

    if (!GEMINI_API_KEY) return reject(new Error('GEMINI_API_KEY not configured'));

    const payload = JSON.stringify({ config: {} });

    const options = {
      hostname: 'generativelanguage.googleapis.com',
      port: 443,
      path: '/v1beta/models/gemini-2.0-flash-live-001:generateEphemeralToken',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload),
        'x-goog-api-key': GEMINI_API_KEY
      }
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data);
          // Expecting response with name and expireTime
          if (parsed && parsed.name && parsed.expireTime) {
            return resolve({ name: parsed.name, expireTime: parsed.expireTime });
          }
          // Some error structure
          return reject(new Error(`Unexpected GenAI response: ${data}`));
        } catch (err) {
          return reject(new Error(`Invalid JSON from GenAI: ${err.message}`));
        }
      });
    });

    req.on('error', (err) => reject(err));
    req.write(payload);
    req.end();
  });
}

function sendGridSendMail(toEmail, toName, subject, htmlBody, plainBody) {
  return new Promise((resolve, reject) => {
    if (!SENDGRID_API_KEY) return reject(new Error('SENDGRID_API_KEY not configured'));

    const payload = JSON.stringify({
      personalizations: [{ to: [{ email: toEmail, name: toName }], subject }],
      from: { email: SENDER_EMAIL, name: SENDER_NAME },
      content: [
        { type: 'text/plain', value: plainBody },
        { type: 'text/html', value: htmlBody }
      ]
    });

    const options = {
      hostname: 'api.sendgrid.com',
      port: 443,
      path: '/v3/mail/send',
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${SENDGRID_API_KEY}`,
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload)
      }
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) return resolve({ status: res.statusCode });
        return reject(new Error(`SendGrid status ${res.statusCode}: ${data}`));
      });
    });

    req.on('error', (err) => reject(err));
    req.write(payload);
    req.end();
  });
}

const server = http.createServer(async (req, res) => {
  try {
    // simple JSON body helper
    const collectBody = () => new Promise(resolve => {
      let b = '';
      req.on('data', chunk => b += chunk);
      req.on('end', () => resolve(b));
    });

    // CORS support (allow frontend origin)
    const ALLOWED_ORIGIN = process.env.CORS_ORIGIN || `https://${SITE_DOMAIN}`;
    res.setHeader('Access-Control-Allow-Origin', ALLOWED_ORIGIN);
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    res.setHeader('Access-Control-Max-Age', '600');

    if (req.method === 'OPTIONS') {
      res.writeHead(204);
      res.end();
      return;
    }

      let b = '';
      req.on('data', chunk => b += chunk);
      req.on('end', () => resolve(b));
    });

    // health
    if (req.url === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'ok' }));
      return;
    }

    // Admin endpoint: generate access URL (optionally email client)
    if (req.url === '/api/admin/generate-access-url' && req.method === 'POST') {
      const clientIP = getClientIP(req);
      const auth = parseAuth(req);
      if (!auth || !SERVICE_SECRET || auth !== SERVICE_SECRET) {
        console.log(`[${new Date().toISOString()}] Unauthorized admin request from ${clientIP}`);
        res.writeHead(401, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Unauthorized' }));
        return;
      }

      const bodyRaw = await collectBody();
      let body = {};
      try { body = bodyRaw ? JSON.parse(bodyRaw) : {}; } catch(e){ body = {}; }

      const accessToken = generateAccessToken();
      accessTokens.set(accessToken, { created: Date.now(), used: false });
      const fingerprint = tokenFingerprint(accessToken);
      const accessUrl = `https://${SITE_DOMAIN}/onboard-secure/?access=${accessToken}`;

      // DO NOT log the full token or URL — only fingerprint
      console.log(`[${new Date().toISOString()}] Access URL generated by ${clientIP} [token:${fingerprint}]`);

      // If an email was provided, send it (best-effort)
      if (body.email) {
        const toEmail = body.email;
        const toName = body.name || '';
        const subject = body.subject || 'Your Private List Consulting Onboarding Link';
        const html = body.html || `Hello ${toName || ''},<br/><br/>Use this secure onboarding link to start your session:<br/><a href="${accessUrl}">${accessUrl}</a><br/><br/>This link expires in ${process.env.ACCESS_TTL_DESC || '24 hours'}.`;
        const plain = body.plain || `Hello ${toName || ''},\n\nUse this secure onboarding link to start your session: ${accessUrl}\n\nThis link expires in ${process.env.ACCESS_TTL_DESC || '24 hours'}.`;

        try {
          await sendGridSendMail(toEmail, toName, subject, html, plain);
          console.log(`[${new Date().toISOString()}] Access URL emailed to ${toEmail} [token:${fingerprint}]`);
        } catch (err) {
          console.error(`[${new Date().toISOString()}] Failed to email access URL to ${toEmail}:`, err.message);
          // continue — return accessUrl to admin regardless
        }
      }

      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ accessUrl, expiresIn: process.env.ACCESS_TTL_DESC || '24 hours' }));
      return;
    }

    // Token exchange endpoint
    if (req.url.startsWith('/api/onboarding-token') && req.method === 'GET') {
      const clientIP = getClientIP(req);
      const urlObj = new URL(req.url, `http://${req.headers.host}`);
      const accessToken = urlObj.searchParams.get('access');

      // If access token provided, validate & consume
      if (accessToken) {
        const fingerprint = tokenFingerprint(accessToken);
        if (!consumeAccessToken(accessToken)) {
          console.log(`[${new Date().toISOString()}] Invalid/used access token from ${clientIP} [token:${fingerprint}]`);
          res.writeHead(401, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Invalid access token', message: 'Token invalid or already used' }));
          return;
        }

        console.log(`[${new Date().toISOString()}] Access token consumed from ${clientIP} [token:${fingerprint}]`);

        try {
          const tokenObj = await createEphemeralToken();
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ token: tokenObj.name, expiresAt: tokenObj.expireTime }));
          console.log(`[${new Date().toISOString()}] Ephemeral token issued for ${clientIP} [token:${fingerprint}]`);
        } catch (err) {
          console.error(`[${new Date().toISOString()}] Failed to create ephemeral token:`, err.message);
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Failed to generate token', message: err.message }));
        }
        return;
      }

      // No access token: fallback to auth header (legacy Model 1 internal flow)
      const auth = parseAuth(req);
      if (auth && SERVICE_SECRET && auth === SERVICE_SECRET) {
        // Legacy flow: issue ephemeral token directly (auth header validated)
        try {
          const tokenObj = await createEphemeralToken();
          // no fingerprint here because we're using auth header flow (internal)
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ token: tokenObj.name, expiresAt: tokenObj.expireTime }));
          console.log(`[${new Date().toISOString()}] Ephemeral token issued via auth header for ${clientIP}`);
        } catch (err) {
          console.error(`[${new Date().toISOString()}] Failed to create ephemeral token (auth header):`, err.message);
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Failed to generate token', message: err.message }));
        }
        return;
      }

      // If we reach here and neither accessToken nor valid auth present
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Bad request', message: 'Missing access token' }));
      return;
    }

    // default 404
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found' }));
  } catch (error) {
    console.error('Server error:', error);
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Server error' }));
  }
});

server.listen(PORT, () => {
  console.log(`Token service listening on port ${PORT}`);
});

module.exports = { server, accessTokens };
