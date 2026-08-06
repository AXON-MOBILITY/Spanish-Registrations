-- Plantilla para crear una organizacion nueva + vincular su primer usuario.
-- Reemplazar 'audi' / 'Audi' / el email segun corresponda. Correr en 2 pasos:
-- 1) Este bloque primero.
-- 2) Crear el usuario en Authentication > Users > Add user con el email
--    indicado abajo (mismo patron: {usuario}@accounts.axonmobility.internal).
-- 3) Volver y correr el bloque final para vincularlo.

-- ── Paso 1: crear la organizacion ───────────────────────────────────────
insert into organizations (slug, display_name, config)
values (
  'audi',
  'Audi',
  '{
    "home_brands": [],
    "focus_brands_source": "custom",
    "use_calibration": false,
    "default_filters": {"years": "latest"}
  }'::jsonb
)
on conflict (slug) do nothing;

-- ── Paso 2: crear el usuario en el Dashboard ────────────────────────────
-- Authentication > Users > Add user
-- Email:    audi@accounts.axonmobility.internal
-- Password: (la que elijas)

-- ── Paso 3: vincular el usuario a la organizacion (correr despues del paso 2) ──
insert into org_members (user_id, org_id, role)
select u.id, o.id, 'admin'
from auth.users u, organizations o
where u.email = 'audi@accounts.axonmobility.internal'
  and o.slug = 'audi'
on conflict (user_id, org_id) do nothing;

-- Verificacion
select o.slug, m.role, u.email
from org_members m
join organizations o on o.id = m.org_id
join auth.users u on u.id = m.user_id;
