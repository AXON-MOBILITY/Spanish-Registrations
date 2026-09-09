// Shared server-only helpers for the /admin panel endpoints (api/admin/*).
// Nothing here ever runs in the browser. The service_role key and the
// encryption key are read from the environment and never leave the server.

const crypto = require('crypto')

const SUPABASE_URL = process.env.SUPABASE_URL || 'https://zuqlmglawucerayjrqam.supabase.co'
const SUPABASE_ANON_KEY =
  process.env.SUPABASE_ANON_KEY || 'sb_publishable_9_fkC1J3JcWiwO9UDLGoFg_aqnTNtMK'
const SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY
const EMAIL_DOMAIN = 'accounts.axonmobility.internal'
const USERNAME_RE = /^[a-z0-9_-]{2,32}$/
// GoTrue has no "ban starting at a future date"; we ban for ~100 years when a
// grant expires and lift it (ban_duration: "none") to re-enable.
const FOREVER_BAN = '876000h'

function svcHeaders(extra) {
  return {
    apikey: SERVICE_ROLE_KEY,
    Authorization: `Bearer ${SERVICE_ROLE_KEY}`,
    'Content-Type': 'application/json',
    ...(extra || {}),
  }
}

async function getCallerUser(token) {
  const r = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
    headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${token}` },
  })
  if (!r.ok) return null
  return r.json()
}

async function isPlatformAdmin(userId) {
  const r = await fetch(
    `${SUPABASE_URL}/rest/v1/platform_admins?user_id=eq.${encodeURIComponent(userId)}&select=user_id`,
    { headers: svcHeaders() },
  )
  if (!r.ok) return false
  return (await r.json()).length > 0
}

// First line of every /api/admin/* handler. Confirms: service key present, a
// bearer session token, a real user, and that user is in platform_admins.
async function requireAdmin(req) {
  if (!SERVICE_ROLE_KEY) return { ok: false, status: 500, error: 'Missing SUPABASE_SERVICE_ROLE_KEY' }
  const header = req.headers.authorization || ''
  const token = header.startsWith('Bearer ') ? header.slice(7) : null
  if (!token) return { ok: false, status: 401, error: 'Missing session' }
  const caller = await getCallerUser(token)
  if (!caller || !caller.id) return { ok: false, status: 401, error: 'Invalid session' }
  if (!(await isPlatformAdmin(caller.id))) {
    return { ok: false, status: 403, error: 'Not a platform admin' }
  }
  return { ok: true, caller }
}

// ---------------------------------------------------------------- crypto
// AES-256-GCM. The key is SHA-256(ADMIN_ENCRYPTION_KEY) so any passphrase works.
// Layout: base64( iv[12] | tag[16] | ciphertext ).
function _key() {
  const raw = process.env.ADMIN_ENCRYPTION_KEY || ''
  return raw ? crypto.createHash('sha256').update(raw, 'utf8').digest() : null
}
function encryptSecret(plain) {
  const key = _key()
  if (!key) return null
  const iv = crypto.randomBytes(12)
  const c = crypto.createCipheriv('aes-256-gcm', key, iv)
  const enc = Buffer.concat([c.update(String(plain), 'utf8'), c.final()])
  return Buffer.concat([iv, c.getAuthTag(), enc]).toString('base64')
}
function decryptSecret(b64) {
  const key = _key()
  if (!key || !b64) return null
  try {
    const buf = Buffer.from(b64, 'base64')
    const d = crypto.createDecipheriv('aes-256-gcm', key, buf.subarray(0, 12))
    d.setAuthTag(buf.subarray(12, 28))
    return Buffer.concat([d.update(buf.subarray(28)), d.final()]).toString('utf8')
  } catch {
    return null
  }
}

// Readable, unambiguous 16-char password (no 0/O/1/l/I).
function genPassword(len = 16) {
  const abc = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
  const bytes = crypto.randomBytes(len)
  let out = ''
  for (let i = 0; i < len; i++) out += abc[bytes[i] % abc.length]
  return out
}

function readBody(req) {
  let body = req.body
  if (typeof body === 'string') {
    try {
      body = JSON.parse(body)
    } catch {
      body = {}
    }
  }
  return body || {}
}

module.exports = {
  SUPABASE_URL,
  SERVICE_ROLE_KEY,
  EMAIL_DOMAIN,
  USERNAME_RE,
  FOREVER_BAN,
  svcHeaders,
  getCallerUser,
  isPlatformAdmin,
  requireAdmin,
  encryptSecret,
  decryptSecret,
  genPassword,
  readBody,
}
