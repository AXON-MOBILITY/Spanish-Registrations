// Vercel Edge Middleware (framework-agnostic — this project has framework:null).
//
// Goal: show the app's own white login screen (public/index.html #login-screen)
// instead of the browser's HTTP Basic pop-up, while keeping every byte of real
// data locked down.
//
// What is public:  the HTML shell, its JS/CSS/images, and POST /api/guest
//                  (needed to mint the guest cookie). The shell carries no
//                  secret — only the Supabase *publishable* anon key — and the
//                  database is behind RLS.
//
// What is gated:   /data/*, /mx/data/* and every other /api/*. A gated request
//                  passes only with ONE of:
//                    1. a valid Supabase session — the `sb-access-token` cookie
//                       index.html mirrors from the SDK, verified here against
//                       the project's pinned ES256 key (no network on the hot
//                       path);
//                    2. a valid guest cookie — `reg-guest`, an HMAC-SHA256
//                       token minted by /api/guest after the shared guest /
//                       MEXICO password, verified here;
//                    3. HTTP Basic Auth — SITE_BASIC_AUTH_USER / _PASS, for the
//                       MX iframe and server-to-server / tooling use.
//
// Fails OPEN only when SITE_BASIC_AUTH_* is unset, so a bad deploy can't lock
// everyone out — clearing those vars is the kill-switch.
//
// User & temporary-access management lives in a SEPARATE Vercel project,
// AXON-MOBILITY/axon-user-admin — not here. This middleware still enforces
// temp-access expiry (app_metadata.expires_at) because those users log in here.

export const config = {
  matcher: '/((?!_vercel/|favicon\\.ico).*)',
}

const SUPABASE_ISSUER = 'https://zuqlmglawucerayjrqam.supabase.co/auth/v1'

// Pinned copy of the project's current ES256 signing key
// (GET https://zuqlmglawucerayjrqam.supabase.co/auth/v1/.well-known/jwks.json).
// Same Supabase project as stock-intelligence-hub, same key id. Set the
// SUPABASE_JWK env var (the JWK as JSON) to override without a redeploy if the
// project ever rotates keys.
const PINNED_JWK = (() => {
  try {
    if (process.env.SUPABASE_JWK) return JSON.parse(process.env.SUPABASE_JWK)
  } catch {}
  return {
    kty: 'EC',
    crv: 'P-256',
    x: 'w7wwry6wmYknxxTB1ZvJwePYR-y1dyucun9YqgEDaBY',
    y: 'ym8O2td-0LhbTO9XS4YHP18sQIS65IrJbGtreeem1SM',
    ext: true,
    key_ops: ['verify'],
  }
})()

function gatedPath(p) {
  return p.startsWith('/data/') || p.startsWith('/mx/data/') || p.startsWith('/api/')
}
// the one /api/ route that must stay reachable without a cookie (it mints one)
function openPath(p) {
  return p === '/api/guest' || p === '/api/guest/'
}

// ------------------------------------------------------------------ helpers
function readCookie(request, name) {
  const jar = request.headers.get('cookie') || ''
  const esc = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const m = jar.match(new RegExp('(?:^|;\\s*)' + esc + '=([^;]*)'))
  return m ? decodeURIComponent(m[1]) : null
}

function b64urlBytes(s) {
  s = s.replace(/-/g, '+').replace(/_/g, '/')
  while (s.length % 4) s += '='
  const bin = atob(s)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

function jsonFromB64url(s) {
  return JSON.parse(new TextDecoder().decode(b64urlBytes(s)))
}

let _jwtKey
function jwtKey() {
  if (!_jwtKey) {
    _jwtKey = crypto.subtle.importKey(
      'jwk', PINNED_JWK, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify'],
    )
  }
  return _jwtKey
}

async function hasSupabaseSession(request) {
  const token = readCookie(request, 'sb-access-token')
  if (!token) return false
  const parts = token.split('.')
  if (parts.length !== 3) return false
  try {
    const [h, p, sig] = parts
    if (jsonFromB64url(h).alg !== 'ES256') return false
    const signed = new TextEncoder().encode(h + '.' + p)
    const ok = await crypto.subtle.verify(
      { name: 'ECDSA', hash: 'SHA-256' }, await jwtKey(), b64urlBytes(sig), signed,
    )
    if (!ok) return false
    const claims = jsonFromB64url(p)
    if (claims.iss !== SUPABASE_ISSUER) return false
    if (claims.role !== 'authenticated') return false
    if (typeof claims.exp === 'number' && claims.exp * 1000 <= Date.now()) return false
    // temporary access: axon-user-admin stamps app_metadata.expires_at; once
    // it's past, the session is dead here even before the token's own exp.
    const grantExp = claims.app_metadata && claims.app_metadata.expires_at
    if (grantExp && Date.parse(grantExp) <= Date.now()) return false
    return true
  } catch {
    return false
  }
}

function guestSecret() {
  return process.env.GUEST_COOKIE_SECRET || process.env.SITE_BASIC_AUTH_PASS || ''
}

let _hmacKey
function hmacKey(secret) {
  if (!_hmacKey) {
    _hmacKey = crypto.subtle.importKey(
      'raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['verify'],
    )
  }
  return _hmacKey
}

// verify an HMAC-SHA256 cookie of shape  <b64url(json)>.<b64url(sig)>
async function verifyHmacCookie(request, name, secret, check) {
  if (!secret) return false
  const raw = readCookie(request, name)
  if (!raw) return false
  const dot = raw.lastIndexOf('.')
  if (dot < 1 || dot === raw.length - 1) return false
  try {
    const payloadB64 = raw.slice(0, dot)
    const ok = await crypto.subtle.verify(
      'HMAC', await hmacKey(secret), b64urlBytes(raw.slice(dot + 1)),
      new TextEncoder().encode(payloadB64),
    )
    if (!ok) return false
    const claims = jsonFromB64url(payloadB64)
    if (!claims || !check(claims)) return false
    if (typeof claims.exp === 'number' && claims.exp * 1000 <= Date.now()) return false
    return true
  } catch {
    return false
  }
}

function hasGuestCookie(request) {
  return verifyHmacCookie(request, 'reg-guest', guestSecret(), (c) => c.g === 1)
}

function isValidBasic(request, user, pass) {
  const header = request.headers.get('authorization') || ''
  const [scheme, encoded] = header.split(' ')
  if (scheme !== 'Basic' || !encoded) return false
  try {
    const decoded = atob(encoded)
    const sep = decoded.indexOf(':')
    if (sep === -1) return false
    return decoded.slice(0, sep) === user && decoded.slice(sep + 1) === pass
  } catch {
    return false
  }
}

function unauthorized(isApi) {
  // No `WWW-Authenticate: Basic` header on purpose: it makes the browser pop
  // its own native Basic-auth dialog on top of the app's styled #login-screen
  // (the shell's parse-time fetch('data/*.json') calls 401 before login).
  // Basic auth still works for callers that send the Authorization header
  // proactively (MX iframe / server-to-server tooling) — see isValidBasic().
  return new Response(isApi ? '{"error":"Unauthorized"}' : 'Authentication required.', {
    status: 401,
    headers: {
      'Content-Type': isApi ? 'application/json' : 'text/plain;charset=UTF-8',
      'Cache-Control': 'no-store',
    },
  })
}

// ------------------------------------------------------------------ entry
export default async function middleware(request) {
  const path = new URL(request.url).pathname
  if (!gatedPath(path) || openPath(path)) return // shell, assets, /api/guest

  const basicUser = process.env.SITE_BASIC_AUTH_USER
  const basicPass = process.env.SITE_BASIC_AUTH_PASS
  if (!basicUser || !basicPass) return // kill-switch: everything open

  if (isValidBasic(request, basicUser, basicPass)) return
  if (await hasSupabaseSession(request)) return
  if (await hasGuestCookie(request)) return

  return unauthorized(path.startsWith('/api/'))
}
