// /api/admin/users
//   GET  -> every account: identity, org, dates, activity, grant status, and
//           (if stored) the last issued password, decrypted.
//   POST -> create an account { username, org_slug?, kind, expires_at?, note? }
//           returns the generated password ONCE (also stored encrypted).
//
// Gated three ways: the Edge middleware requires a Supabase session cookie to
// reach /api/*, requireAdmin() re-verifies the bearer token AND platform_admins
// membership, and the service_role key never leaves this process.

const {
  SUPABASE_URL, EMAIL_DOMAIN, USERNAME_RE,
  svcHeaders, requireAdmin, encryptSecret, decryptSecret, genPassword, readBody,
} = require('../../lib/admin')

async function listAuthUsers() {
  const out = []
  for (let page = 1; page <= 20; page++) {
    const r = await fetch(
      `${SUPABASE_URL}/auth/v1/admin/users?page=${page}&per_page=200`,
      { headers: svcHeaders() },
    )
    if (!r.ok) break
    const body = await r.json()
    const users = Array.isArray(body) ? body : body.users || []
    out.push(...users)
    if (users.length < 200) break
  }
  return out
}

async function fetchJson(path) {
  const r = await fetch(`${SUPABASE_URL}${path}`, { headers: svcHeaders() })
  return r.ok ? r.json() : []
}

module.exports = async (req, res) => {
  const gate = await requireAdmin(req)
  if (!gate.ok) return res.status(gate.status).json({ error: gate.error })

  // -------------------------------------------------- GET: list everything
  if (req.method === 'GET') {
    const [users, members, orgs, grants, admins] = await Promise.all([
      listAuthUsers(),
      fetchJson('/rest/v1/org_members?select=user_id,org_id,role'),
      fetchJson('/rest/v1/organizations?select=id,slug,display_name'),
      fetchJson('/rest/v1/access_grants?select=*'),
      fetchJson('/rest/v1/platform_admins?select=user_id'),
    ])
    const orgById = Object.fromEntries(orgs.map((o) => [o.id, o]))
    const memberByUser = Object.fromEntries(members.map((m) => [m.user_id, m]))
    const grantByUser = Object.fromEntries(grants.map((g) => [g.user_id, g]))
    const adminSet = new Set(admins.map((a) => a.user_id))
    const now = Date.now()

    const rows = users.map((u) => {
      const m = memberByUser[u.id]
      const org = m ? orgById[m.org_id] : null
      const g = grantByUser[u.id]
      const expiresAt = g?.expires_at || u.app_metadata?.expires_at || null
      const bannedUntil = u.banned_until && new Date(u.banned_until) > new Date() ? u.banned_until : null
      let status = 'active'
      if (adminSet.has(u.id)) status = 'admin'
      else if (bannedUntil || g?.revoked_at) status = 'revoked'
      else if (expiresAt && Date.parse(expiresAt) <= now) status = 'expired'
      else if (expiresAt) status = 'expiring'
      return {
        user_id: u.id,
        username: (u.email || '').split('@')[0],
        email: u.email,
        org: org ? org.display_name : null,
        org_slug: org ? org.slug : g?.org_slug || null,
        is_platform_admin: adminSet.has(u.id),
        created_at: u.created_at,
        last_sign_in_at: u.last_sign_in_at || null,
        days_in_use: u.created_at
          ? Math.floor((now - Date.parse(u.created_at)) / 86400000)
          : null,
        kind: g?.kind || (expiresAt ? 'temporary' : 'permanent'),
        expires_at: expiresAt,
        days_left: expiresAt
          ? Math.ceil((Date.parse(expiresAt) - now) / 86400000)
          : null,
        revoked_at: g?.revoked_at || null,
        banned_until: bannedUntil,
        note: g?.note || null,
        password: g?.pw_cipher ? decryptSecret(g.pw_cipher) : null,
        status,
      }
    })
    rows.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
    const orgList = orgs
      .map((o) => ({ slug: o.slug, display_name: o.display_name }))
      .sort((a, b) => a.display_name.localeCompare(b.display_name))
    return res.status(200).json({ ok: true, count: rows.length, users: rows, orgs: orgList })
  }

  // -------------------------------------------------- POST: create account
  if (req.method === 'POST') {
    const { username, org_slug, kind = 'temporary', expires_at, note } = readBody(req)
    const uname = String(username || '').trim().toLowerCase()
    if (!USERNAME_RE.test(uname)) {
      return res.status(400).json({ error: 'Invalid username (a-z 0-9 - _, 2-32 chars)' })
    }
    if (kind !== 'temporary' && kind !== 'permanent') {
      return res.status(400).json({ error: 'kind must be "temporary" or "permanent"' })
    }
    let expiresIso = null
    if (kind === 'temporary') {
      const t = Date.parse(expires_at || '')
      if (!t || t <= Date.now()) {
        return res.status(400).json({ error: 'temporary access needs a future expires_at' })
      }
      expiresIso = new Date(t).toISOString()
    }

    let orgId = null
    if (org_slug) {
      const orgs = await fetchJson(`/rest/v1/organizations?slug=eq.${encodeURIComponent(org_slug)}&select=id`)
      if (!orgs.length) return res.status(400).json({ error: `Unknown org_slug "${org_slug}"` })
      orgId = orgs[0].id
    }

    const email = `${uname}@${EMAIL_DOMAIN}`
    const password = genPassword()

    const createResp = await fetch(`${SUPABASE_URL}/auth/v1/admin/users`, {
      method: 'POST',
      headers: svcHeaders(),
      body: JSON.stringify({
        email,
        password,
        email_confirm: true,
        app_metadata: expiresIso
          ? { kind, expires_at: expiresIso, issued_by: gate.caller.id }
          : { kind, issued_by: gate.caller.id },
      }),
    })
    if (!createResp.ok) {
      const detail = await createResp.text()
      return res.status(409).json({ error: 'Could not create user (already exists?)', detail })
    }
    const newUser = await createResp.json()

    if (orgId) {
      await fetch(`${SUPABASE_URL}/rest/v1/org_members`, {
        method: 'POST',
        headers: svcHeaders(),
        body: JSON.stringify({ user_id: newUser.id, org_id: orgId, role: 'member' }),
      })
    }

    const grantResp = await fetch(`${SUPABASE_URL}/rest/v1/access_grants`, {
      method: 'POST',
      headers: svcHeaders({ Prefer: 'resolution=merge-duplicates' }),
      body: JSON.stringify({
        user_id: newUser.id,
        username: uname,
        org_slug: org_slug || null,
        kind,
        expires_at: expiresIso,
        pw_cipher: encryptSecret(password),
        note: note || null,
        issued_by: gate.caller.id,
      }),
    })
    if (!grantResp.ok) {
      const detail = await grantResp.text()
      // user exists and works; only the ledger row failed
      return res.status(207).json({
        ok: true, username: uname, password, warning: 'user created but ledger insert failed', detail,
      })
    }

    return res.status(200).json({ ok: true, username: uname, password, expires_at: expiresIso })
  }

  res.setHeader('Allow', 'GET, POST')
  return res.status(405).json({ error: 'Method not allowed' })
}
