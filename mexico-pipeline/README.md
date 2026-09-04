# Mexico pipeline (RAIAVL / INEGI)

Ported from the standalone `Mexico-Registrations` repo. Feeds the **MEXICO** view
of this app: a separate static dashboard served at `/mx`, gated by the password
`AXONMOBILITY2026` (typed on `/mx` directly, or reached from the main login by
signing in with username `MEXICO`).

## Refresh the data

```bash
pip install -r mexico-pipeline/requirements.txt
python mexico-pipeline/refresh.py
```

`refresh.py` runs the five scripts in order and copies the generated JSON into
`public/mx/data/`:

| step | writes |
|---|---|
| `scripts/download_inegi.py` | downloads + unzips the RAIAVL open-data ZIPs to `data/raw/` |
| `scripts/process_data.py` | `data/processed/mx_registrations.csv` (venta, from 2023, + `enrich.py`) |
| `scripts/process_export_data.py` | `data/processed/mx_exports.csv` |
| `scripts/process_production_data.py` | `data/processed/mx_production.csv` |
| `scripts/build_dashboard_data.py` | `public/data/records*.json` + `meta*.json` |

Then review `public/mx/data/*.json`, commit them, and push -- Vercel serves the
static file, no build step.

INEGI publishes new figures ~mid-to-late each month for the previous month and
revises preliminary numbers later, so `download_inegi.py` always overwrites.

`data/` and `public/` here are intermediate/reproducible and gitignored; only
`../public/mx/data/*.json` ships.

## Dashboard

`public/mx/index.html` is the standalone Mexico dashboard, vendored as-is except
that absolute asset paths were prefixed with `/mx` and a client-side password
gate was added at the top of `<body>`. Its tabs (Overview / Ranking / Trend /
Exportación / Producción) and the "Origen" dimension differ from the Spanish
dashboard because the RAIAVL source is a national monthly aggregate with no
province, dealer, or sales-channel breakdown. See `METODOLOGIA.md` for how
`fuel_type` / `body_type` are derived.
