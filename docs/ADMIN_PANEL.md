# Admin panel — user & access management

`/admin` on the deployed site (`registrations.axon-mobility.com/admin`). A
single-page console for the platform operator to see **every account**, when it
was created, how long it has been in use, when it was last used, and to hand out
**temporary user/password access** that expires on its own.

> TL;DR to bring it up: run one SQL file, set two env vars, add yourself to
> `platform_admins`, redeploy. Details below.

---

## 1. What it shows / does

| Column | Source |
|---|---|
| Usuario | Supabase Auth email local-part (`cliente@accounts.axonmobility.internal` → `cliente`) |
| Org | `org_members` → `organizations.display_name` (blank = generic view) |
| Alta | `auth.users.created_at` |
| Días en uso | `now − created_at` |
| Último acceso | `auth.users.last_sign_in_at` |
| Estado | `Activo` / `Caducado` / `Revocado` / `Admin` (derived) |
| Caduca | `access_grants.expires_at` + días restantes |
| Contraseña | last password issued **through the panel**, AES-256-GCM at rest, shown decrypted |

Actions per row: **resetear** contraseña · **extender** caducidad · **hacer
permanente** · **revocar** (bloquea ya) · **borrar** (elimina la cuenta).

"Nuevo acceso" form: username + Temporal/Permanente + fecha de caducidad + org
(opcional) + nota. On create it returns a generated 16-char password **once** and
also stores it encrypted so you can look it up later in the table.

### About passwords

Supabase stores password **hashes** (bcrypt) — the passwords that already exist
cannot be shown, by anyone, ever. The panel therefore:

- **generates** the password when it creates an account, shows it once, and keeps
  an **encrypted** copy (`access_grants.pw_cipher`) that only the server can read;
- lets you **reset** to a new generated password at any time;
- shows `no registrada` for accounts created before this panel or outside it —
  reset them once to start tracking a password.

There is **no plaintext credential table**. If the Supabase DB leaked, the
`pw_cipher` values are useless without `ADMIN_ENCRYPTION_KEY` (which lives only in
Vercel env, never in the repo or the DB).

---

## 2. Security model

Four independent gates protect every admin API call. All must pass.

```
browser ─► Edge middleware ──────────────► /api/admin/* handler ─► Supabase
           (0) admin-gate cookie/Basic      (2) bearer token +      (3) service_role
               (ADMIN_GATE_USER/PASS)           platform_admins         key server-only
           (1) Supabase session cookie          membership
```

**Gate 0 — the extra /admin credential.** `/admin`, `/admin.html` and
`/api/admin/*` sit behind a second, standalone user/password
(`ADMIN_GATE_USER` / `ADMIN_GATE_PASS`), separate from any Supabase account.
Reaching `/admin` with no `admin-gate` cookie serves a small unlock form; `POST
/api/admin-unlock` checks the pair and sets the HMAC-signed `admin-gate` cookie
(HttpOnly, Secure, SameSite=Lax, 8h, secret = `ADMIN_GATE_SECRET` → falls back
to `GUEST_COOKIE_SECRET` → `SITE_BASIC_AUTH_PASS`). `/api/admin/*` also accepts
`Authorization: Basic ADMIN_GATE_USER:PASS` for curl/tooling. **If
`ADMIN_GATE_*` is unset this layer is skipped** (the three below still apply) —
so set it to actually lock the panel down.

0. **The `admin-gate` credential** (see above) — `/admin`, `/admin.html` and
   `/api/admin/*` need it before anything else. A cracked Supabase session still
   can't reach the panel without this second password.
1. **Edge middleware** (`middleware.js`). `/api/admin/*` is under `/api/`, so it
   is unreachable without a valid Supabase **session cookie** (`sb-access-token`,
   ES256-verified against the project's pinned key) or HTTP Basic. See
   [`SECURITY.md`](./SECURITY.md).
2. **Handler guard** (`lib/admin.js` → `requireAdmin`). Re-reads the `Authorization:
   Bearer <token>`, calls Supabase `/auth/v1/user` to confirm it is a real live
   session, then checks the caller's `user_id` is in `platform_admins`. 401/403
   otherwise. The middleware cookie and this bearer are checked **separately** —
   spoofing one does not help.
3. **service_role key** (`SUPABASE_SERVICE_ROLE_KEY`). The only key that can list
   users or write `access_grants`. It is read from env inside the serverless
   function and never sent to the browser, never logged, never in the repo.

Supporting controls:

- **`access_grants` has RLS on and zero policies** → no `anon` or `authenticated`
  client can read or write it. Only `service_role` (which bypasses RLS) touches
  it, i.e. only `/api/admin/*`.
- **Password encryption**: AES-256-GCM, key = `SHA-256(ADMIN_ENCRYPTION_KEY)`,
  random 12-byte IV per value, GCM tag verified on decrypt (tampering → null).
- **Protected accounts**: `user-actions` refuses to modify or delete anyone in
  `platform_admins` or the primary `bmw@…` account.
- **Cron auth**: `/api/admin/sweep` only runs for `Authorization: Bearer
  <CRON_SECRET>` (Vercel Cron) or a normal admin bearer. The middleware lets the
  cron request through *only* when that exact secret is present; the handler
  re-checks it.
- **Generated passwords**: 16 chars from a 55-symbol alphabet with `0/O/1/l/I`
  removed, `crypto.randomBytes`. ~92 bits of entropy.

### Threat model — what is and isn't covered

| Covered | Not covered / accepted |
|---|---|
| DB leak → stored passwords stay encrypted | If **`ADMIN_ENCRYPTION_KEY` leaks too**, stored passwords are exposed. Rotate the key + reset all temp passwords. |
| Non-admin authenticated user hitting `/api/admin/*` → 403 | A compromised **platform-admin session** has full control. Keep that account's password strong; 2FA on the operator's own machine. |
| Forged / expired / wrong-key session tokens → rejected at the edge | Revoke has up to ~1h latency for an **already-issued** access token (until it refreshes and the middleware sees the new `expires_at`). Cron + ban make it permanent. |
| Temporary access auto-expires with no manual step | Clock skew between Vercel edge and Supabase (seconds) — irrelevant at day granularity. |
| `access_grants` unreadable by clients (RLS) | The panel HTML itself is a public static file — it contains **no secrets**, only the publishable anon key, same as `index.html`. |

---

## 3. Setup (one time)

### 3.1 Database

Supabase → SQL Editor → run:

```
supabase/admin_access_grants.sql
```

Creates `access_grants` (RLS on, no policies). Safe to re-run.

### 3.2 Environment variables (Vercel → Settings → Environment Variables)

| Name | Type | Value | Notes |
|---|---|---|---|
| `SUPABASE_SERVICE_ROLE_KEY` | Secret | *(already set)* | used by all `/api/admin/*` and the existing `create-org`/`delete-org` |
| `ADMIN_ENCRYPTION_KEY` | Secret | a long random string (≥32 chars) | encrypts stored passwords. **Back it up.** Lose it → stored passwords unrecoverable (accounts still work; just reset them). |
| `CRON_SECRET` | Secret | a long random string | Vercel Cron sends it as a bearer to `/api/admin/sweep`; nothing else may call the cron path unauthenticated |
| `ADMIN_GATE_USER` | Secret | a username | the extra credential in front of `/admin`. **Set this to lock the panel down** — unset = layer skipped. |
| `ADMIN_GATE_PASS` | Secret | a strong password | pair for `ADMIN_GATE_USER` |
| `ADMIN_GATE_SECRET` | Secret | *(optional)* long random string | signs the `admin-gate` cookie; falls back to `GUEST_COOKIE_SECRET` then `SITE_BASIC_AUTH_PASS` |

Generate values with e.g. `node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"`.
Set for **Production** (and Preview if you test there). Redeploy after adding.

### 3.3 Make yourself a platform admin

Supabase → SQL Editor:

```sql
insert into platform_admins (user_id)
select id from auth.users
where email = 'YOURUSER@accounts.axonmobility.internal'
on conflict do nothing;
```

(`platform_admins` already exists — see `supabase/platform_admins.sql`.)

### 3.4 Cron

`vercel.json` already declares:

```json
"crons": [{ "path": "/api/admin/sweep", "schedule": "0 3 * * *" }]
```

Vercel picks it up on the next production deploy (Pro plan). It runs daily at
03:00 UTC. You can also trigger it by hand from the panel is not wired, but
`GET /api/admin/sweep` with your admin bearer works.

---

## 4. Daily use

### Give someone temporary access
1. `/admin` → **Nuevo acceso**.
2. Username (lowercase, `a-z 0-9 - _`), **Temporal**, pick **Caduca** date, org
   optional, note optional → **Crear acceso**.
3. Copy the `usuario / contraseña` shown. Send it to them.
4. They log in at `registrations.axon-mobility.com` like any account.

### While it's live
- The row shows **días en uso**, **último acceso**, and **días restantes**.
- **extender** to push the date out; **hacer permanente** to remove the expiry;
  **resetear** for a fresh password; **revocar** to cut access immediately.

### When it expires
- On/after the date the person can no longer log in (enforced at the edge and by
  the daily sweep, which also flips the row to *Revocado*).
- 30 days after expiry the sweep **deletes** the account entirely (auth user +
  `org_members` + `access_grants` via cascade). Extend before then to keep it.

---

## 5. How expiry is enforced (defence in depth)

| Layer | Mechanism | Latency |
|---|---|---|
| **Edge middleware** | rejects any session whose JWT `app_metadata.expires_at` is past — every `/data`, `/mx/data`, `/api` request | immediate on next token refresh (≤1h), then every request |
| **Daily sweep** (`/api/admin/sweep`) | bans the Supabase user (`ban_duration` ≈ 100y) once expired → login itself fails; deletes after 30-day grace | ≤24h to ban, then permanent |
| **Panel `revocar`** | bans now + stamps `expires_at = now` so the edge drops the session on next refresh | ≤1h for an active token, immediate for new logins |

Permanent accounts have no `expires_at` and are never touched by any of these.

---

## 6. Files

| Path | Role |
|---|---|
| `public/admin.html` | the console (static, no secrets, self-gating) |
| `api/admin-unlock.js` | `POST`/`DELETE` the `admin-gate` cookie (the extra credential) |
| `lib/admin.js` | shared server helpers: `requireAdmin`, AES-GCM crypto, password gen |
| `api/admin/users.js` | `GET` list everything · `POST` create account |
| `api/admin/user-actions.js` | `POST` reset / extend / make_permanent / revoke / delete |
| `api/admin/sweep.js` | cron: ban expired, delete after grace |
| `supabase/admin_access_grants.sql` | the `access_grants` ledger (RLS, no policies) |
| `middleware.js` | edge gate + expiry check + cron-path allowance |
| `vercel.json` | `/admin` rewrite + cron schedule |

---

## 7. Endpoint reference

All require `Authorization: Bearer <supabase access token of a platform admin>`,
the `sb-access-token` cookie, **and** the `admin-gate` cookie (or
`Authorization: Basic ADMIN_GATE_USER:PASS`) once `ADMIN_GATE_*` is set.

### `POST /api/admin-unlock`
body `{ user, password }` checked against `ADMIN_GATE_USER` / `ADMIN_GATE_PASS`
→ `Set-Cookie: admin-gate=…` (8h). `DELETE` clears it. Open (no auth needed to
reach it).

### `GET /api/admin/users`
→ `{ ok, count, users: [ { user_id, username, email, org, org_slug,
is_platform_admin, created_at, last_sign_in_at, days_in_use, kind, expires_at,
days_left, revoked_at, banned_until, note, password, status } ], orgs: [ {slug,
display_name} ] }`

### `POST /api/admin/users`
body `{ username, org_slug?, kind: "temporary"|"permanent", expires_at?, note? }`
→ `{ ok, username, password, expires_at }` — **`password` is shown once here** and
also stored encrypted.

### `POST /api/admin/user-actions`
body `{ action, user_id, expires_at? }`

| action | effect | returns |
|---|---|---|
| `reset_password` | new generated password, updates `pw_cipher` | `{ ok, username, password }` |
| `extend` | needs `expires_at`; lifts ban, updates grant + `app_metadata` | `{ ok, expires_at }` |
| `make_permanent` | drops the expiry, lifts ban | `{ ok }` |
| `revoke` | bans now, stamps `revoked_at` + `expires_at=now` | `{ ok }` |
| `delete` | deletes the auth user (cascades) | `{ ok }` |

Refuses `platform_admins` members and the `bmw@…` account.

### `GET /api/admin/sweep`
Cron or admin. Bans grants past `expires_at`, deletes those past
`expires_at + 30d`. → `{ ok, checked, banned, deleted, errors }`
