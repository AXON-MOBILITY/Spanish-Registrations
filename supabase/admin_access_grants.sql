-- Admin panel — access grant ledger.
-- Run once in Supabase → SQL Editor. Safe to re-run.
--
-- One row per user account that the /admin panel issued (or adopted). It records
-- WHEN the access was granted, WHEN it expires, and — encrypted — the last
-- password handed out, so the operator can look up "what did I give this client"
-- without a plaintext credential column.
--
-- Security:
--   * RLS is ON and there are NO policies -> no client (anon or authenticated)
--     can read or write this table. Only the service_role key (used exclusively
--     by /api/admin/* on the server) bypasses RLS.
--   * pw_cipher is AES-256-GCM (see lib/admin.js). Losing ADMIN_ENCRYPTION_KEY
--     makes stored passwords unrecoverable — reset them, they are not lost from
--     Supabase Auth itself.

create table if not exists access_grants (
  user_id     uuid primary key references auth.users(id) on delete cascade,
  username    text not null,
  org_slug    text,                                   -- null = no org (generic view)
  kind        text not null default 'temporary'
                check (kind in ('temporary', 'permanent')),
  expires_at  timestamptz,                            -- null when kind = 'permanent'
  pw_cipher   text,                                   -- AES-256-GCM(base64) of last issued password
  note        text,
  issued_at   timestamptz not null default now(),
  issued_by   uuid references auth.users(id) on delete set null,
  revoked_at  timestamptz                             -- set when banned by admin or by the sweep
);

alter table access_grants enable row level security;
-- deliberately no policies: service_role only.

create index if not exists access_grants_expires_idx
  on access_grants (expires_at) where kind = 'temporary';
