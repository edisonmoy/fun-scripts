// Jev vs the old Haiku quick pass on the sorting step. Run with
//   JEV_API_KEY=... ANTHROPIC_API_KEY=... npm run eval:sorting
// Optional: RUNS (default 3), SYSTEMS (default "jev,haiku").
//
// Both sides run the real production code paths: Jev through sortThread,
// and the new pipeline's follow-up Haiku extraction through classify().
// Token usage is captured by wrapping fetch / the Anthropic client, and
// priced at published rates (metrics.js). Writes full results to
// evals/sorting/results/ (gitignored) and prints a summary.

import Anthropic from '@anthropic-ai/sdk'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { it } from 'vitest'
import { classify, needsResearch } from '../../lib/triage/classifier'
import { RESEARCH_MODEL } from '../../lib/triage/config'
import { sortThread } from '../../lib/triage/jev'
import { CASES, PREFERENCES } from './dataset'
import { haikuQuickClassify } from './haikuBaseline'
import { costUsd, flipRate, PRICES, scoreRun } from './metrics'

const RUNS = Number(process.env.RUNS || 3)
const SYSTEMS = (process.env.SYSTEMS || 'jev,haiku').split(',').map((s) => s.trim())
const CONCURRENCY = 4
const HERE = dirname(fileURLToPath(import.meta.url))
const hasAnthropicKey = Boolean(process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN)

async function mapLimit(items, limit, fn) {
  const results = new Array(items.length)
  let next = 0
  await Promise.all(
    Array.from({ length: limit }, async () => {
      while (next < items.length) {
        const i = next++
        results[i] = await fn(items[i])
      }
    })
  )
  return results
}

async function timed(fn) {
  const start = performance.now()
  try {
    return { ...(await fn()), latencyMs: performance.now() - start, error: null }
  } catch (err) {
    return { prediction: null, latencyMs: performance.now() - start, error: err.message }
  }
}

// Jev: production sortThread, with fetch wrapped to read `usage`.
async function runJev(c) {
  let usage = null
  const fetchImpl = async (url, init) => {
    const res = await fetch(url, init)
    if (res.ok) usage = (await res.clone().json()).usage ?? null
    return res
  }
  const row = await timed(async () => ({ prediction: await sortThread(c, PREFERENCES, fetchImpl) }))
  return { case: c, ...row, usage, costUsd: costUsd(usage, PRICES.jev) }
}

async function runHaiku(c, client) {
  const row = await timed(async () => {
    const { result, usage } = await haikuQuickClassify(c, PREFERENCES, client)
    return { prediction: result, usage }
  })
  return { case: c, ...row, costUsd: costUsd(row.usage, PRICES.haiku) }
}

// Cost of the Haiku extraction pass the Jev pipeline adds for mail that
// gets a reply but isn't escalated. Runs production classify() with the
// research model blocked (research costs the same per call either way, so
// it's compared by escalation count instead).
async function extractionCost(c, anthropic) {
  let usage = null
  const client = {
    messages: {
      create: async (req) => {
        if (req.model === RESEARCH_MODEL) throw new Error('research skipped in eval')
        const res = await anthropic.messages.create(req)
        usage = res.usage
        return res
      },
    },
  }
  await classify(c, PREFERENCES, { client })
  return costUsd(usage, PRICES.haiku)
}

function fmt(v, kind) {
  if (v === null || v === undefined) return '-'
  if (kind === 'pct') return `${(v * 100).toFixed(1)}%`
  if (kind === 'usd') return `$${v.toFixed(4)}`
  if (kind === 'ms') return `${Math.round(v)}ms`
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}

function mean(values) {
  const xs = values.filter((v) => typeof v === 'number')
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null
}

it(
  'sorting eval: Jev vs Haiku',
  async () => {
    const runs = {}
    const anthropic = hasAnthropicKey ? new Anthropic() : null

    for (const system of SYSTEMS) {
      if (system === 'haiku' && !anthropic) {
        console.warn('Skipping haiku: no ANTHROPIC_API_KEY set.')
        continue
      }
      runs[system] = []
      for (let r = 0; r < RUNS; r++) {
        const fn = system === 'jev' ? runJev : (c) => runHaiku(c, anthropic)
        runs[system].push(await mapLimit(CASES, CONCURRENCY, fn))
      }
    }

    // Full sorting-stage pipeline cost for Jev: Jev on every email, plus
    // the extraction pass on non-ignored, non-escalated mail (first run).
    let jevPipelinePer1k = null
    if (runs.jev && anthropic) {
      const needsExtract = runs.jev[0].filter(
        (r) => r.prediction && r.prediction.category !== 'ignore' && !needsResearch(r.prediction)
      )
      const extractCosts = await mapLimit(needsExtract, CONCURRENCY, (r) =>
        extractionCost(r.case, anthropic).catch(() => 0)
      )
      const total =
        runs.jev[0].reduce((s, r) => s + r.costUsd, 0) + extractCosts.reduce((s, x) => s + x, 0)
      jevPipelinePer1k = (total / CASES.length) * 1000
    }

    const summary = {}
    for (const [system, systemRuns] of Object.entries(runs)) {
      const scores = systemRuns.map(scoreRun)
      const avg = (key) => mean(scores.map((s) => s[key]))
      summary[system] = {
        runs: scores.length,
        outreachAccuracy: avg('outreachAccuracy'),
        categoryAccuracy: avg('categoryAccuracy'),
        unambiguousCategoryAccuracy: avg('unambiguousCategoryAccuracy'),
        highInterestRecall: avg('highInterestRecall'),
        escalationPrecision: avg('escalationPrecision'),
        escalations: avg('escalations'),
        lostReplies: avg('lostReplies'),
        errors: avg('errors'),
        latencyP50Ms: avg('latencyP50Ms'),
        latencyP95Ms: avg('latencyP95Ms'),
        sortCostPer1kEmailsUsd: avg('costPer1kEmailsUsd'),
        flipRate: flipRate(systemRuns),
        perRun: scores,
      }
    }
    if (summary.jev) summary.jev.pipelineCostPer1kEmailsUsd = jevPipelinePer1k
    if (summary.haiku) summary.haiku.pipelineCostPer1kEmailsUsd = summary.haiku.sortCostPer1kEmailsUsd

    const rows = [
      ['Outreach accuracy', 'outreachAccuracy', 'pct'],
      ['Category accuracy', 'categoryAccuracy', 'pct'],
      ['  (unambiguous only)', 'unambiguousCategoryAccuracy', 'pct'],
      ['High-interest recall', 'highInterestRecall', 'pct'],
      ['Escalation precision', 'escalationPrecision', 'pct'],
      ['Research escalations', 'escalations', ''],
      ['Replies lost (-> ignore)', 'lostReplies', ''],
      ['Errors', 'errors', ''],
      ['Latency p50', 'latencyP50Ms', 'ms'],
      ['Latency p95', 'latencyP95Ms', 'ms'],
      ['Sort cost / 1k emails', 'sortCostPer1kEmailsUsd', 'usd'],
      ['Pipeline cost / 1k emails', 'pipelineCostPer1kEmailsUsd', 'usd'],
      ['Run-to-run flip rate', 'flipRate', 'pct'],
    ]
    const systems = Object.keys(summary)
    const lines = [
      `Sorting eval: ${CASES.length} cases x ${RUNS} runs`,
      ['Metric'.padEnd(28), ...systems.map((s) => s.padStart(12))].join(''),
      ...rows.map(([label, key, kind]) =>
        [label.padEnd(28), ...systems.map((s) => fmt(summary[s][key], kind).padStart(12))].join('')
      ),
    ]
    for (const s of systems) {
      lines.push('', `${s} misses (run 1): ` + JSON.stringify(summary[s].perRun[0].misses))
    }
    process.stderr.write(lines.join('\n') + '\n')

    const dir = join(HERE, 'results')
    mkdirSync(dir, { recursive: true })
    const file = join(dir, `${new Date().toISOString().replace(/[:.]/g, '-')}.json`)
    writeFileSync(
      file,
      JSON.stringify({ cases: CASES.length, runs: RUNS, summary, raw: runs }, null, 2)
    )
    process.stderr.write(`\nFull results: ${file}\n`)
  },
  30 * 60 * 1000
)
