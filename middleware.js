// Vercel Edge Middleware (framework-agnostic — this project has framework:null).
//
// Without this, the raw datasets are downloadable by anyone:
//   https://registrations.axon-mobility.com/data/records.json      (~3.3 MB)
//   https://registrations.axon-mobility.com/mx/data/records.json
// The dashboard's own login only gates the UI, not the JSON underneath it.
//
// Runs on every request except Vercel internals, so the dashboard HTML, every
// /data/*.json and /mx/data/*.json file, and the /api/* functions all require
// the shared HTTP Basic credential.
//
// Fails OPEN when SITE_BASIC_AUTH_USER / SITE_BASIC_AUTH_PASS are unset, so
// deploying this file alone changes nothing until the env vars are set (and
// removing them is the instant kill-switch).

export const config = {
  matcher: '/((?!_vercel/|favicon\\.ico).*)',
}

function unauthorized() {
  return new Response('Authentication required.', {
    status: 401,
    headers: {
      'WWW-Authenticate': 'Basic realm="Axon Registrations", charset="UTF-8"',
      'Cache-Control': 'no-store',
    },
  })
}

export default function middleware(request) {
  const expectedUser = process.env.SITE_BASIC_AUTH_USER
  const expectedPass = process.env.SITE_BASIC_AUTH_PASS
  if (!expectedUser || !expectedPass) return

  const header = request.headers.get('authorization') || ''
  const [scheme, encoded] = header.split(' ')
  if (scheme === 'Basic' && encoded) {
    let decoded = ''
    try {
      decoded = atob(encoded)
    } catch {
      return unauthorized()
    }
    const sep = decoded.indexOf(':')
    if (sep !== -1) {
      const user = decoded.slice(0, sep)
      const pass = decoded.slice(sep + 1)
      if (user === expectedUser && pass === expectedPass) return
    }
  }
  return unauthorized()
}
