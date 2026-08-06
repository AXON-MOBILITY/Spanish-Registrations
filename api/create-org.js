// Crea una organizacion nueva + su primer usuario.
// Unico lugar del proyecto donde se usa la SUPABASE_SERVICE_ROLE_KEY (nunca
// llega al navegador). Protegido: valida el token de quien llama y exige
// que figure en platform_admins antes de hacer nada.

const SUPABASE_URL = process.env.SUPABASE_URL || 'https://oazxgmzhwqbfyfanwiir.supabase.co';
const SUPABASE_ANON_KEY = process.env.SUPABASE_ANON_KEY || 'sb_publishable_XI9OEZpCHlZ8ZCAbjGA7UQ_1lAxsZBG';
const SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
const EMAIL_DOMAIN = 'accounts.axonmobility.internal';

const SLUG_RE = /^[a-z0-9_-]{2,32}$/;

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
    res.status(403).json({ error: 'You do not have permission to create organizations' });
    return;
  }

  const { slug, display_name, username, password, config } = req.body || {};
  if (!slug || !SLUG_RE.test(slug)) {
    res.status(400).json({ error: 'Invalid slug (use lowercase letters, numbers, dashes, 2-32 characters)' });
    return;
  }
  if (!display_name || !String(display_name).trim()) {
    res.status(400).json({ error: 'Missing organization name' });
    return;
  }
  const uname = String(username || '').trim().toLowerCase();
  if (!uname || !SLUG_RE.test(uname)) {
    res.status(400).json({ error: 'Invalid username (use lowercase letters, numbers, dashes, 2-32 characters)' });
    return;
  }
  if (!password || String(password).length < 8) {
    res.status(400).json({ error: 'Password must be at least 8 characters long' });
    return;
  }

  const email = `${uname}@${EMAIL_DOMAIN}`;
  const svcHeaders = {
    apikey: SERVICE_ROLE_KEY,
    Authorization: `Bearer ${SERVICE_ROLE_KEY}`,
    'Content-Type': 'application/json',
  };

  // 1) Crear organizacion
  const orgResp = await fetch(`${SUPABASE_URL}/rest/v1/organizations`, {
    method: 'POST',
    headers: { ...svcHeaders, Prefer: 'return=representation' },
    body: JSON.stringify({
      slug,
      display_name,
      config: config || { home_brands: [], focus_brands: [], use_calibration: false, default_filters: { years: 'latest' } },
    }),
  });
  if (!orgResp.ok) {
    const detail = await orgResp.text();
    res.status(409).json({ error: 'Could not create the organization (does the slug already exist?)', detail });
    return;
  }
  const [org] = await orgResp.json();

  // 2) Crear usuario (Admin API)
  const userResp = await fetch(`${SUPABASE_URL}/auth/v1/admin/users`, {
    method: 'POST',
    headers: svcHeaders,
    body: JSON.stringify({ email, password, email_confirm: true }),
  });
  if (!userResp.ok) {
    const detail = await userResp.text();
    res.status(409).json({ error: 'Organization created, but the user could not be created (already exists?)', org, detail });
    return;
  }
  const newUser = await userResp.json();

  // 3) Vincular usuario <-> organizacion
  const linkResp = await fetch(`${SUPABASE_URL}/rest/v1/org_members`, {
    method: 'POST',
    headers: svcHeaders,
    body: JSON.stringify({ user_id: newUser.id, org_id: org.id, role: 'admin' }),
  });
  if (!linkResp.ok) {
    const detail = await linkResp.text();
    res.status(500).json({ error: 'User and organization created, but linking failed. Link them manually.', org, user: newUser.id, detail });
    return;
  }

  res.status(200).json({ ok: true, org: { slug: org.slug, display_name: org.display_name }, username: uname });
};
