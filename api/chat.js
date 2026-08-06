// Serverless AI assistant for Spanish Registrations (vehicle registrations /
// market share). Plain Node (Vercel auto-detects any api/*.js file as a
// Serverless Function even on a framework:null static project), calling the
// Gemini REST API directly with fetch - no npm dependency needed, so this
// stays a zero-build static site plus one function.
//
// Data is aggregated server-side from the same public/data/*.json files the
// dashboard itself reads, fetched from this deployment's own origin. Only
// the small/medium files are used (meta, forecast, daily_mtd, provinces,
// daily_brands) - the multi-MB per-record files (records*.json,
// province_brands.json) are deliberately left out; they'd blow the prompt
// budget for very little extra value in a chat answer.

const MODEL_CANDIDATES = ['gemini-3.5-flash-lite', 'gemini-2.5-flash', 'gemini-flash-latest']

async function fetchJson(base, path) {
  try {
    const res = await fetch(`${base}${path}`)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

function pad2(n) {
  return String(n).padStart(2, '0')
}

// daily_brands.json stores each brand as a 9-value array: canal (3) x fuel
// (3) flattened as canalIndex*3 + fuelIndex, confirmed against the
// dashboard's own trend-chart code (index.html, initTrend/renderTrend).
function aggregateBrandShareForMonth(dailyBrands, yearMonth) {
  if (!dailyBrands || !dailyBrands.days) return []
  const totals = {}
  for (const day of dailyBrands.days) {
    if (!day.day.startsWith(yearMonth)) continue
    for (const [brand, values] of Object.entries(day.brands || {})) {
      const sum = (values || []).reduce((s, n) => s + (n || 0), 0)
      totals[brand] = (totals[brand] || 0) + sum
    }
  }
  const grandTotal = Object.values(totals).reduce((s, n) => s + n, 0)
  return Object.entries(totals)
    .map(([brand, units]) => ({ brand, units, sharePct: grandTotal ? +(units / grandTotal * 100).toFixed(2) : 0 }))
    .sort((a, b) => b.units - a.units)
    .slice(0, 25)
}

function buildContext({ meta, forecast, dailyMtd, provinces, dailyBrands }) {
  const targetMonth = dailyMtd ? `${dailyMtd.year}-${pad2(dailyMtd.month)}` : (meta?.current_mtd ? `${meta.current_mtd.year}-${pad2(meta.current_mtd.month)}` : null)
  const latestDay = dailyMtd?.days?.[dailyMtd.days.length - 1] || null

  return {
    meta: meta ? {
      updated: meta.updated,
      lastCompletedMonth: meta.last_completed_month,
      currentMonthLabel: meta.current_mtd?.label,
      totalRegistrationsHistorical: meta.total_registrations_historical,
    } : null,
    monthToDate: latestDay ? {
      month: dailyMtd.month_label + ' ' + dailyMtd.year,
      daysElapsed: latestDay.day,
      cumulative: latestDay.cumul,
    } : null,
    brandMarketShareThisMonth: targetMonth ? aggregateBrandShareForMonth(dailyBrands, targetMonth) : [],
    brandForecast: forecast?.brands ? [...forecast.brands]
      .sort((a, b) => b.share_hat - a.share_hat)
      .slice(0, 20)
      .map(b => ({ brand: b.marca, ytdUnits: b.ytd_exrac, forecastSharePct: +(b.share_hat * 100).toFixed(2), forecastYearUnits: b.year_base_exrac })) : [],
    marketForecast: forecast?.market ? {
      targetMonth: forecast.target_month,
      monthToDateUnits: forecast.market.mtd_exrac,
      forecastMonthUnits: forecast.market.f_month_exrac_base,
      ytdUnits: forecast.market.ytd_exrac,
      forecastYearUnits: forecast.market.year_base_exrac,
    } : null,
    topProvinces: provinces?.provinces ? [...provinces.provinces]
      .sort((a, b) => b.total - a.total)
      .slice(0, 20)
      .map(p => ({ province: p.name, total: p.total, private: p.Private, corporate: p.Corporate, rac: p.RAC, ice: p.ICE, bev: p.BEV, phev: p.PHEV })) : [],
  }
}

module.exports = async (req, res) => {
  if (req.method !== 'POST') {
    res.status(405).json({ reply: 'Method not allowed' })
    return
  }

  const apiKey = process.env.GEMINI_API_KEY
  if (!apiKey) {
    res.status(500).json({ reply: 'Error: API key not configured.' })
    return
  }

  try {
    const chunks = []
    for await (const chunk of req) chunks.push(chunk)
    const { message } = JSON.parse(Buffer.concat(chunks).toString('utf-8') || '{}')
    if (!message || !String(message).trim()) {
      res.status(400).json({ reply: 'Empty message.' })
      return
    }

    const base = `https://${req.headers.host}`
    const [meta, forecast, dailyMtd, provinces, dailyBrands] = await Promise.all([
      fetchJson(base, '/data/meta.json'),
      fetchJson(base, '/data/forecast.json'),
      fetchJson(base, '/data/daily_mtd.json'),
      fetchJson(base, '/data/provinces.json'),
      fetchJson(base, '/data/daily_brands.json'),
    ])
    const context = buildContext({ meta, forecast, dailyMtd, provinces, dailyBrands })

    const prompt = `You are an AI assistant for Axon Mobility - Spanish Registrations, a tool tracking Spanish new-vehicle registrations (matriculaciones) and brand market share, sourced from DGT data.

Real-time data:
- meta: dataset freshness and coverage
- monthToDate: current month's cumulative registrations by channel (Private/Corporate/RAC) and fuel (ICE/BEV/PHEV)
- brandMarketShareThisMonth: ACTUAL registrations and market share % by brand for the current month so far, from raw daily data
- brandForecast: model-projected market share % and full-year units by brand
- marketForecast: total market projection for the current month and year
- topProvinces: registrations by province, with channel and fuel breakdown

${JSON.stringify(context, null, 2)}

Rules:
- Be concise and use bullet points for lists
- Always cite specific numbers/percentages from the data
- Clearly distinguish ACTUAL month-to-date data (brandMarketShareThisMonth, monthToDate) from FORECAST/projected data (brandForecast, marketForecast) - never blend them without saying which is which
- Respond in the same language the user writes in (Spanish or English)

User question: ${message}`

    let lastErr = null
    for (const modelId of MODEL_CANDIDATES) {
      try {
        const geminiRes = await fetch(
          `https://generativelanguage.googleapis.com/v1beta/models/${modelId}:generateContent?key=${apiKey}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] }),
          }
        )
        const data = await geminiRes.json()
        if (!geminiRes.ok) throw new Error(data?.error?.message || `HTTP ${geminiRes.status}`)
        const text = data?.candidates?.[0]?.content?.parts?.map(p => p.text).join('') || ''
        if (!text) throw new Error('Empty response from model')
        res.status(200).json({ reply: text })
        return
      } catch (err) {
        lastErr = err
        console.error(`Gemini error on ${modelId}:`, err?.message || err)
      }
    }
    throw lastErr
  } catch (err) {
    console.error('Chat error:', err?.message || err)
    res.status(500).json({ reply: `Error: ${err?.message || 'Unknown error'}` })
  }
}
