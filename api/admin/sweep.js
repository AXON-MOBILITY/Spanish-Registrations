// /api/admin/sweep  (GET) — the daily janitor for temporary access.
//
//   expires_at passed            -> ban the user (ban_duration = ~100y), stamp
//                                   revoked_at, mark app_metadata expired.
//   expires_at passed > 30 days  -> delete the auth user entirely
//                                   (org_members + access_grants cascade).
//
// Auth: Vercel Cron sends `Authorization: Bearer <CRON_SECRET>` when the
// CRON_SECRET env var is set. A platform admin may also call it by hand with a
// normal bearer token. Nothing else gets in (the Edge middleware also blocks
// the path unless one of those is present).

const {
  SUPABASE_URL, FOREVER_BAN, svcHeaders, requireAdmin,
} = require('../../lib/admin')

const GRACE_MS = 30 * 24 * 60 * 60 * 1000

module.exports = async (req, res) => {
  const cronSecret = process.env.CRON_SECRET
  const isCron = cronSecret && req.headers.authorization === `Bearer ${cronSecret}`
  if (!isCron) {
    const gate = await requireAdmin(req)
    if (!gate.ok) return res.status(gate.status).json({ error: gate.error })
  }

  const nowIso = new Date().toISOString()
  const r = await fetch(
    `${SUPABASE_URL}/rest/v1/access_grants?kind=eq.temporary&expires_at=lt.${encodeURIComponent(nowIso)}&select=user_id,expires_at,revoked_at`,
    { headers: svcHeaders() },
  )
  if (!r.ok) return res.status(502).json({ error: 'Could not read access_grants', detail: await r.text() })
  const due = await r.json()

  const now = Date.now()
  let banned = 0
  let deleted = 0
  const errors = []

  for (const g of due) {
    const past = now - Date.parse(g.expires_at)
    try {
      if (past > GRACE_MS) {
        const d = await fetch(`${SUPABASE_URL}/auth/v1/admin/users/${g.user_id}`, {
          method: 'DELETE', headers: svcHeaders(),
        })
        if (d.ok) deleted++
        else errors.push({ user_id: g.user_id, step: 'delete', detail: await d.text() })
      } else if (!g.revoked_at) {
        const u = await fetch(`${SUPABASE_URL}/auth/v1/admin/users/${g.user_id}`, {
          method: 'PUT',
          headers: svcHeaders(),
          body: JSON.stringify({ ban_duration: FOREVER_BAN }),
        })
        if (u.ok) {
          banned++
          await fetch(`${SUPABASE_URL}/rest/v1/access_grants?user_id=eq.${g.user_id}`, {
            method: 'PATCH',
            headers: svcHeaders({ Prefer: 'return=minimal' }),
            body: JSON.stringify({ revoked_at: nowIso }),
          })
        } else {
          errors.push({ user_id: g.user_id, step: 'ban', detail: await u.text() })
        }
      }
    } catch (e) {
      errors.push({ user_id: g.user_id, step: 'exception', detail: String(e) })
    }
  }

  return res.status(200).json({ ok: true, checked: due.length, banned, deleted, errors })
}
