-- Administradores de plataforma: quien puede crear organizaciones nuevas.
-- Distinto de org_members.role='admin' (que solo administra SU propia org).
-- Correr en el SQL Editor de Supabase.

create table if not exists platform_admins (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);

alter table platform_admins enable row level security;

-- Un usuario puede consultar unicamente si EL MISMO es admin (para mostrar
-- u ocultar el panel en el frontend). Nadie puede ver la lista completa ni
-- escribir desde el cliente: crear filas aca es exclusivo de la funcion de
-- servidor (usa la service_role key, que ignora RLS).
drop policy if exists "platform_admins: select own" on platform_admins;
create policy "platform_admins: select own" on platform_admins
  for select using (user_id = auth.uid());

-- ── Marcar al usuario BMW actual como admin de plataforma ───────────────
insert into platform_admins (user_id)
select u.id from auth.users u
where u.email = 'bmw@accounts.axonmobility.internal'
on conflict (user_id) do nothing;

-- Verificacion
select u.email, pa.created_at
from platform_admins pa
join auth.users u on u.id = pa.user_id;
