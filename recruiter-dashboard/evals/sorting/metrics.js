import { needsResearch } from '../../lib/triage/classifier'

// Published per-million-token prices (USD). Jev bills input only.
export const PRICES = {
  jev: { input: 0.042, output: 0 },
  haiku: { input: 1.0, output: 5.0 },
  sonnet: { input: 2.0, output: 10.0 },
  opus: { input: 5.0, output: 25.0 },
}

export const CATEGORIES = ['ignore', 'keep_warm', 'high_interest']

export function costUsd(usage, price) {
  if (!usage) return 0
  return ((usage.input_tokens || 0) * price.input + (usage.output_tokens || 0) * price.output) / 1e6
}

function percentile(values, p) {
  if (values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  return sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)]
}

const ratio = (num, den) => (den === 0 ? null : num / den)

// rows: [{case, prediction|null, error|null, latencyMs, costUsd}] for one
// system and one run. Errors count as wrong on every metric.
export function scoreRun(rows) {
  const confusion = Object.fromEntries(
    CATEGORIES.map((g) => [g, Object.fromEntries(CATEGORIES.map((p) => [p, 0]))])
  )
  let outreachRight = 0
  let categoryRight = 0
  let unambiguous = 0
  let unambiguousRight = 0
  let escalateTp = 0
  let escalateFp = 0
  let escalateFn = 0
  let lostReplies = 0
  let errors = 0
  const misses = []

  for (const { case: c, prediction: p, error } of rows) {
    const gold = c.gold
    if (error || !p) {
      errors++
      misses.push({ id: c.id, gold: gold.category, got: 'ERROR' })
      if (gold.category === 'high_interest') escalateFn++
      continue
    }
    if (p.is_recruiter_outreach === gold.is_recruiter_outreach) outreachRight++
    confusion[gold.category][p.category]++
    const right = p.category === gold.category
    if (right) categoryRight++
    else misses.push({ id: c.id, gold: gold.category, got: p.category, fit: p.fit_score })
    if (!c.ambiguous) {
      unambiguous++
      if (right) unambiguousRight++
    }

    // Escalation = the expensive research pass. It should fire for
    // high-interest mail and nothing else.
    const escalated = needsResearch(p)
    const shouldEscalate = gold.category === 'high_interest'
    if (escalated && shouldEscalate) escalateTp++
    else if (escalated) escalateFp++
    else if (shouldEscalate) escalateFn++

    // Worst error: real outreach that deserves a reply sorted as ignore, so
    // no draft is ever written.
    if (gold.category !== 'ignore' && p.category === 'ignore') lostReplies++
  }

  const n = rows.length
  const latencies = rows.filter((r) => !r.error).map((r) => r.latencyMs)
  const totalCost = rows.reduce((sum, r) => sum + (r.costUsd || 0), 0)
  return {
    n,
    errors,
    outreachAccuracy: ratio(outreachRight, n),
    categoryAccuracy: ratio(categoryRight, n),
    unambiguousCategoryAccuracy: ratio(unambiguousRight, unambiguous),
    highInterestRecall: ratio(escalateTp, escalateTp + escalateFn),
    escalationPrecision: ratio(escalateTp, escalateTp + escalateFp),
    escalations: escalateTp + escalateFp,
    lostReplies,
    latencyP50Ms: percentile(latencies, 50),
    latencyP95Ms: percentile(latencies, 95),
    costPer1kEmailsUsd: n ? (totalCost / n) * 1000 : 0,
    confusion,
    misses,
  }
}

// How often a system gives the same case different categories across runs.
export function flipRate(runs) {
  if (runs.length < 2) return null
  const byCase = new Map()
  for (const rows of runs) {
    for (const r of rows) {
      if (!byCase.has(r.case.id)) byCase.set(r.case.id, new Set())
      byCase.get(r.case.id).add(r.prediction?.category ?? 'ERROR')
    }
  }
  const flipped = [...byCase.values()].filter((s) => s.size > 1).length
  return flipped / byCase.size
}
