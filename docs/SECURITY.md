# Access control — architecture

How `registrations.axon-mobility.com` decides who may see the dashboards and the
raw datasets. Framework is `null` (static `public/` + serverless `api/` + one
Edge middleware). User management is a separate project — see below.

## The gate: `middleware.js` (Vercel Edge)

Runs on every request. **Public**: the HTML shell, its JS/CSS/images, and
`POST /api/guest`. **Gated**: `/data/*`, `/mx/data/*`, and every other `/api/*`.

A gated request passes with **one** of:

| Credential | Verified how |
|---|---|
| **Supabase session** | `sb-access-token` cookie (the SDK access token, mirrored into a cookie by `index.html`). ES256 signature checked against the project's **pinned JWK** with Web Crypto — no network on the hot path. Rejected if: bad signature, wrong `iss`, `role ≠ authenticated`, `exp` past, or **`app_metadata.expires_at` past** (temporary-access cutoff). |
| **Guest cookie** | `reg-guest` — an HMAC-SHA256 token minted by `POST /api/guest` after the shared guest / MEXICO password. `HttpOnly`, `Secure`, `SameSite=Lax`, 12 h. HMAC re-verified on every request with `GUEST_COOKIE_SECRET` (falls back to `SITE_BASIC_AUTH_PASS`). Unforgeable without the secret. |
| **HTTP Basic** | `SITE_BASIC_AUTH_USER` / `_PASS` — for the MX iframe and server-to-server / tooling use. |

Special cases:
- `POST /api/guest` is open (mint endpoint; password-checked inside).

**Kill-switch**: if `SITE_BASIC_AUTH_USER` / `_PASS` are unset the middleware
fails **open** (everything public) so a bad deploy can't lock the team out.
Clearing those two vars is the deliberate "open it all up" lever.

## Why the HTML shell is public

To render the app's own white login screen instead of the browser's Basic Auth
pop-up. The shell carries **no secret** — only the Supabase *publishable* anon
key (same as any Supabase SPA). Everything that returns real data is behind the
gate, and the database is behind RLS.

## User & temporary-access management

Not in this repo. It's a separate Vercel project,
**`AXON-MOBILITY/axon-user-admin`**, that talks to the same Supabase project.
This app only *enforces* what it sets: a temporary account's session dies here
once its `app_metadata.expires_at` passes (checked in `hasSupabaseSession`).

## Session lifecycle (`index.html`)

1. On load, synchronously read the SDK's persisted session from `localStorage`
   and write the `sb-access-token` cookie **before** the first `fetch('/data…')`.
2. `onAuthStateChange` rewrites the cookie on refresh, clears it on sign-out.
3. Fresh login / guest entry does a one-time `location.reload()` so the
   parse-time data fetches re-run authenticated.

## Roles

| Role | Stored in | Can |
|---|---|---|
| guest / MEXICO | shared password → `reg-guest` cookie | view dashboards (generic org) |
| org user | `auth.users` + `org_members` | view dashboards as their org |
| org admin | `org_members.role = 'admin'` | + edit their org's settings |
| **platform admin** | `platform_admins` | + the `axon-user-admin` console: manage all users & access |

`platform_admins` has RLS `select using (user_id = auth.uid())` — a user can only
see whether *they themselves* are an admin. The full list and all writes are
service-role-only.

## Server-only secrets (Vercel env, never in repo / DB / browser)

| Var | Used by | Notes |
|---|---|---|
| `SUPABASE_SERVICE_ROLE_KEY` | `api/create-org`, `api/delete-org` | bypasses RLS; the crown jewel |
| `SITE_BASIC_AUTH_USER` / `_PASS` | `middleware.js` | Basic Auth + guest-cookie HMAC fallback secret |
| `GUEST_COOKIE_SECRET` | `middleware.js`, `api/guest` | optional dedicated HMAC key for `reg-guest` |
| `GUEST_PASSWORD` | `api/guest` | shared guest / MEXICO password (default `AXONMOBILITY2026`) |
| `SUPABASE_JWK` | `middleware.js` | optional — override the pinned session-signing key without a redeploy |

(The `axon-user-admin` project has its own set: `ADMIN_ENCRYPTION_KEY`,
`CRON_SECRET`, `ADMIN_GATE_USER/PASS`, `ADMIN_GATE_SECRET`.)

## What each layer does NOT protect against

- A compromised **service-role key** = full control. Treat it as a top secret.
- Temp-access expiry has ≤1 h latency for an **already-issued** access token
  (until it refreshes); `axon-user-admin`'s ban + daily sweep make it permanent.
- The guest password is **shared** — rotate `GUEST_PASSWORD` (or the fallback
  `AXONMOBILITY2026`) if it leaks; that invalidates all `reg-guest` cookies.

User-management console: see `AXON-MOBILITY/axon-user-admin` (`docs/ADMIN_PANEL.md`).
