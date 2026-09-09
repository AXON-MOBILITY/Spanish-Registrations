// /api/admin/user-actions  (POST)
// { action: 'reset_password' | 'extend' | 'revoke' | 'make_permanent' | 'delete',
//   user_id, expires_at? }
//
// Same three-way gate as /api/admin/users. Refuses to touch platform admins or
// the primary bmw account.

const {
  SUPABASE_URL, FOREVER_BAN,
  svcHeaders, requireAdmin, isPlatformAdmin, encryptSecret, genPassword, readBody,
} = require('../../lib/admin')

async function getUser(id) {
  const r = await fetch(`${SUPABASE_URL}/auth/v1/admin/users/${id}`, { headers: svcHeaders() })
  return r.ok ? r.json() : null
}
async function putUser(id, patch) {
  return fetch(`${SUPABASE_URL}/auth/v1/admin/users/${id}`, {
    method: 'PUT', headers: svcHeaders(), body: JSON.stringify(patch),
  })
}
async function patchGrant(id, patch) {
  return fetch(`${SUPABASE_URL}/rest/v1/access_grants?user_id=eq.${id}`, {
    method: 'PATCH', headers: svcHeaders({ Prefer: 'return=minimal' }), body: JSON.stringify(patch),
  })
}

module.exports = async (req, res) => {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST')
    return res.status(405).json({ error: 'Method not allowed' })
  }
  const gate = await requireAdmin(req)
  if (!gate.ok) return res.status(gate.status).json({ error: gate.error })

  const { action, user_id, expires_at } = readBody(req)
  if (!user_id || typeof user_id !== 'string') {
    return res.status(400).json({ error: 'Missing user_id' })
  }

  const target = await getUser(user_id)
  if (!target) return res.status(404).json({ error: 'User not found' })
  if (target.email === 'bmw@accounts.axonmobility.internal') {
    return res.status(400).json({ error: 'The bmw account is protected' })
  }
  if (await isPlatformAdmin(user_id)) {
    return res.status(400).json({ error: 'Platform admins cannot be modified from here' })
  }
  const meta = target.app_metadata || {}

  switch (action) {
    case 'reset_password': {
      const password = genPassword()
      const r = await putUser(user_id, { password })
      if (!r.ok) return res.status(502).json({ error: 'Reset failed', detail: await r.text() })
      await patchGrant(user_id, { pw_cipher: encryptSecret(password) })
      return res.status(200).json({ ok: true, username: (target.email || '').split('@')[0], password })
    }

    case 'extend': {
      const t = Date.parse(expires_at || '')
      if (!t || t <= Date.now()) return res.status(400).json({ error: 'extend needs a future expires_at' })
      const iso = new Date(t).toISOString()
      const r = await putUser(user_id, {
        ban_duration: 'none',
        app_metadata: { ...meta, kind: 'temporary', expires_at: iso },
      })
      if (!r.ok) return res.status(502).json({ error: 'Extend failed', detail: await r.text() })
      await patchGrant(user_id, { kind: 'temporary', expires_at: iso, revoked_at: null })
      return res.status(200).json({ ok: true, expires_at: iso })
    }

    case 'make_permanent': {
      const nextMeta = { ...meta, kind: 'permanent' }
      delete nextMeta.expires_at
      const r = await putUser(user_id, { ban_duration: 'none', app_metadata: nextMeta })
      if (!r.ok) return res.status(502).json({ error: 'Update failed', detail: await r.text() })
      await patchGrant(user_id, { kind: 'permanent', expires_at: null, revoked_at: null })
      return res.status(200).json({ ok: true })
    }

    case 'revoke': {
      // ban + mark expired now, so the middleware drops the session on next token refresh
      const r = await putUser(user_id, {
        ban_duration: FOREVER_BAN,
        app_metadata: { ...meta, expires_at: new Date().toISOString() },
      })
      if (!r.ok) return res.status(502).json({ error: 'Revoke failed', detail: await r.text() })
      await patchGrant(user_id, { revoked_at: new Date().toISOString() })
      return res.status(200).json({ ok: true })
    }

    case 'delete': {
      const r = await fetch(`${SUPABASE_URL}/auth/v1/admin/users/${user_id}`, {
        method: 'DELETE', headers: svcHeaders(),
      })
      if (!r.ok) return res.status(502).json({ error: 'Delete failed', detail: await r.text() })
      // org_members + access_grants rows drop via ON DELETE CASCADE
      return res.status(200).json({ ok: true })
    }

    default:
      return res.status(400).json({ error: `Unknown action "${action}"` })
  }
}
