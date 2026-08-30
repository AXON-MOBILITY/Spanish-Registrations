// Borra una organizacion: su/s usuario/s de Supabase Auth, el vinculo en
// org_members, y la fila en organizations. Igual que create-org.js, el
// unico lugar donde se usa la SUPABASE_SERVICE_ROLE_KEY es aca, nunca en
// el navegador. Protegido: exige que quien llama figure en platform_admins.

const SUPABASE_URL = process.env.SUPABASE_URL || 'https://zuqlmglawucerayjrqam.supabase.co';
const SUPABASE_ANON_KEY = process.env.SUPABASE_ANON_KEY || 'sb_publishable_9_fkC1J3JcWiwO9UDLGoFg_aqnTNtMK';
const SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;

async function getCallerUser(token) {
  const r = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
    headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${token}` },
  });
  if (!r.ok) return null;
  return r.json();
}

async function isPlatformAdmin(userId) {
  const r = await fetch(
    `${SUPABASE_URL}/rest/v1/platform_admins?user_id=eq.${userId}&select=user_id`,
    { headers: { apikey: SERVICE_ROLE_KEY, Authorization: `Bearer ${SERVICE_ROLE_KEY}` } }
  );
  if (!r.ok) return false;
  const rows = await r.json();
  return rows.length > 0;
}

module.exports = async (req, res) => {
  if (req.method !== 'POST') {
    res.status(405).json({ error: 'Method not allowed' });
    return;
  }
  if (!SERVICE_ROLE_KEY) {
    res.status(500).json({ error: 'Missing SUPABASE_SERVICE_ROLE_KEY in Vercel environment variables' });
    return;
  }

  const authHeader = req.headers.authorization || '';
  const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : null;
  if (!token) {
    res.status(401).json({ error: 'Missing session' });
    return;
  }
  const caller = await getCallerUser(token);
  if (!caller || !caller.id) {
    res.status(401).json({ error: 'Invalid session' });
    return;
  }
  const admin = await isPlatformAdmin(caller.id);
  if (!admin) {
    res.status(403).json({ error: 'You do not have permission to delete organizations' });
    return;
  }

  const { slug } = req.body || {};
  if (!slug || typeof slug !== 'string') {
    res.status(400).json({ error: 'Missing slug' });
    return;
  }
  if (slug === 'bmw') {
    res.status(400).json({ error: 'The BMW organization cannot be deleted' });
    return;
  }

  const svcHeaders = {
    apikey: SERVICE_ROLE_KEY,
    Authorization: `Bearer ${SERVICE_ROLE_KEY}`,
    'Content-Type': 'application/json',
  };

  // 1) Encontrar la organizacion
  const orgResp = await fetch(`${SUPABASE_URL}/rest/v1/organizations?slug=eq.${encodeURIComponent(slug)}&select=id`, {
    headers: svcHeaders,
  });
  if (!orgResp.ok) {
    res.status(500).json({ error: 'Could not look up the organization' });
    return;
  }
  const orgs = await orgResp.json();
  if (!orgs.length) {
    res.status(404).json({ error: 'Organization not found' });
    return;
  }
  const orgId = orgs[0].id;

  // 2) Encontrar sus usuarios (org_members)
  const membersResp = await fetch(`${SUPABASE_URL}/rest/v1/org_members?org_id=eq.${orgId}&select=user_id`, {
    headers: svcHeaders,
  });
  const members = membersResp.ok ? await membersResp.json() : [];

  // 3) Borrar org_members, luego la organizacion
  await fetch(`${SUPABASE_URL}/rest/v1/org_members?org_id=eq.${orgId}`, { method: 'DELETE', headers: svcHeaders });
  const delOrgResp = await fetch(`${SUPABASE_URL}/rest/v1/organizations?id=eq.${orgId}`, { method: 'DELETE', headers: svcHeaders });
  if (!delOrgResp.ok) {
    const detail = await delOrgResp.text();
    res.status(500).json({ error: 'Could not delete the organization', detail });
    return;
  }

  // 4) Borrar los usuarios de Auth (best-effort, no bloquea si alguno falla)
  const userErrors = [];
  for (const m of members) {
    const r = await fetch(`${SUPABASE_URL}/auth/v1/admin/users/${m.user_id}`, { method: 'DELETE', headers: svcHeaders });
    if (!r.ok) userErrors.push(m.user_id);
  }

  res.status(200).json({ ok: true, slug, usersDeleted: members.length - userErrors.length, userErrors });
};
