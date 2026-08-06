-- Axon Mobility — esquema multi-organización
-- Correr en Supabase → SQL Editor → New query → Run
-- Seguro de re-ejecutar (usa IF NOT EXISTS / OR REPLACE en todos lados).

create extension if not exists "pgcrypto";

-- ── Organizaciones (BMW, AUDI, ...) ─────────────────────────────────────
create table if not exists organizations (
  id           uuid primary key default gen_random_uuid(),
  slug         text unique not null,          -- 'bmw', 'audi' (minusculas, sin espacios)
  display_name text not null,                 -- 'BMW', 'Audi'
  config       jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);

comment on column organizations.config is
  'home_brands: string[] (marca(s) resaltada(s)); '
  'focus_brands: string[] (set competitivo propio, define Focus vs Resto); '
  'default_filters: objeto con years/months/segs/subs/hps por defecto; '
  'use_calibration: bool (si aplica la calibracion SIMMIX o usa dato DGT neutro)';

-- ── Vínculo usuario (Supabase Auth) → organización ──────────────────────
create table if not exists org_members (
  user_id  uuid references auth.users(id) on delete cascade,
  org_id   uuid references organizations(id) on delete cascade,
  role     text not null default 'member',   -- 'admin' | 'member'
  primary key (user_id, org_id)
);

-- ── Row Level Security: cada usuario solo ve/edita su propia org ───────
alter table organizations enable row level security;
alter table org_members enable row level security;

drop policy if exists "org: select own" on organizations;
create policy "org: select own" on organizations
  for select using (
    id in (select org_id from org_members where user_id = auth.uid())
  );

drop policy if exists "org: update own" on organizations;
create policy "org: update own" on organizations
  for update using (
    id in (select org_id from org_members where user_id = auth.uid())
  );

drop policy if exists "org_members: select own" on org_members;
create policy "org_members: select own" on org_members
  for select using (user_id = auth.uid());

-- ── Seed: organización BMW con la config actual (clon 1:1 de lo existente) ──
insert into organizations (slug, display_name, config)
values (
  'bmw',
  'BMW',
  '{
    "home_brands": ["BMW", "MINI"],
    "focus_brands_source": "legacy_simmix",
    "use_calibration": true,
    "default_filters": {"years": "latest"}
  }'::jsonb
)
on conflict (slug) do nothing;
