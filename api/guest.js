// Mints (POST) or clears (DELETE) the shared "guest" session cookie `reg-guest`
// that the Edge middleware accepts for /data, /mx/data and /api.
//
// Guest access is a shared client-side gate, not an account — the dashboard
// datasets are otherwise static. The dedicated MEXICO view uses this same
// endpoint with the same shared password.
//
// The cookie is an HMAC-SHA256 token: `<b64url(payload)>.<b64url(sig)>` where
// payload = {"g":1,"exp":<unix>} and sig = HMAC(payload, GUEST_COOKIE_SECRET).
// Unforgeable without the secret; the middleware verifies it on every request.

const crypto = require('crypto')

const GUEST_PASSWORD = process.env.GUEST_PASSWORD || 'AXONMOBILITY2026'
const SECRET = process.env.GUEST_COOKIE_SECRET || process.env.SITE_BASIC_AUTH_PASS || ''
const MAX_AGE = 12 * 60 * 60 // 12h

const b64url = (buf) =>
  Buffer.from(buf).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

function mintToken() {
  const payload = b64url(JSON.stringify({ g: 1, exp: Math.floor(Date.now() / 1000) + MAX_AGE }))
  const sig = b64url(crypto.createHmac('sha256', SECRET).update(payload).digest())
  return payload + '.' + sig
}

const CLEAR = 'reg-guest=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0'

module.exports = async (req, res) => {
  if (req.method === 'DELETE') {
    res.setHeader('Set-Cookie', CLEAR)
    res.status(200).json({ ok: true })
    return
  }
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST, DELETE')
    res.status(405).json({ error: 'Method not allowed' })
    return
  }
  if (!SECRET) {
    res.status(500).json({ error: 'Guest cookie secret not configured' })
    return
  }

  let body = req.body
  if (typeof body === 'string') {
    try { body = JSON.parse(body) } catch { body = {} }
  }
  const password = body && body.password
  const expected = Buffer.from(String(GUEST_PASSWORD))
  const got = Buffer.from(String(password || ''))
  const ok = got.length === expected.length && crypto.timingSafeEqual(got, expected)
  if (!ok) {
    res.status(401).json({ error: 'Incorrect password' })
    return
  }

  res.setHeader(
    'Set-Cookie',
    `reg-guest=${mintToken()}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${MAX_AGE}`,
  )
  res.status(200).json({ ok: true })
}
