// Mints (POST) / clears (DELETE) the `admin-gate` cookie — the extra credential
// in front of /admin and /api/admin/*, independent of the Supabase session and
// the platform_admins check the panel already enforces.
//
// POST { user, password } checked against ADMIN_GATE_USER / ADMIN_GATE_PASS.
// Cookie: `<b64url({"a":1,"exp":<unix>})>.<b64url(HMAC-SHA256(payload, secret))>`,
// HttpOnly/Secure/SameSite=Lax, 8h. Secret = ADMIN_GATE_SECRET, falling back to
// GUEST_COOKIE_SECRET then SITE_BASIC_AUTH_PASS. Unforgeable without it.

const crypto = require('crypto')

const GATE_USER = process.env.ADMIN_GATE_USER || ''
const GATE_PASS = process.env.ADMIN_GATE_PASS || ''
const SECRET =
  process.env.ADMIN_GATE_SECRET ||
  process.env.GUEST_COOKIE_SECRET ||
  process.env.SITE_BASIC_AUTH_PASS ||
  ''
const MAX_AGE = 8 * 60 * 60 // 8h

const b64url = (buf) =>
  Buffer.from(buf).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

function mintToken() {
  const payload = b64url(JSON.stringify({ a: 1, exp: Math.floor(Date.now() / 1000) + MAX_AGE }))
  const sig = b64url(crypto.createHmac('sha256', SECRET).update(payload).digest())
  return payload + '.' + sig
}

const eq = (a, b) => {
  const x = Buffer.from(String(a || ''))
  const y = Buffer.from(String(b || ''))
  return x.length === y.length && crypto.timingSafeEqual(x, y)
}

const CLEAR = 'admin-gate=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0'

module.exports = async (req, res) => {
  if (req.method === 'DELETE') {
    res.setHeader('Set-Cookie', CLEAR)
    return res.status(200).json({ ok: true })
  }
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST, DELETE')
    return res.status(405).json({ error: 'Method not allowed' })
  }
  if (!GATE_USER || !GATE_PASS || !SECRET) {
    return res.status(503).json({ error: 'Admin gate not configured' })
  }

  let body = req.body
  if (typeof body === 'string') {
    try { body = JSON.parse(body) } catch { body = {} }
  }
  const { user, password } = body || {}
  if (!eq(user, GATE_USER) || !eq(password, GATE_PASS)) {
    return res.status(401).json({ error: 'Incorrect credentials' })
  }

  res.setHeader(
    'Set-Cookie',
    `admin-gate=${mintToken()}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${MAX_AGE}`,
  )
  return res.status(200).json({ ok: true })
}
