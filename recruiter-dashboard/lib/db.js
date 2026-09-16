// Postgres access for the recruiter dashboard: a single shared `pg` Pool,
// plus a one-time-per-cold-start idempotent schema apply so this app never
// depends on the gmail-recruiter-triage job having run first.

import { Pool } from 'pg'
import fs from 'node:fs'
import path from 'node:path'

// Reuse the pool (and the "schema applied" flag) across hot-reloads in dev
// and across warm serverless invocations, instead of opening a new pool
// per request.
const globalForDb = globalThis

function createPool() {
  const connectionString = process.env.DATABASE_URL
  if (!connectionString) {
    throw new Error('DATABASE_URL is not set')
  }
  return new Pool({ connectionString })
}

export function getPool() {
  if (!globalForDb.__recruiterDashboardPool) {
    globalForDb.__recruiterDashboardPool = createPool()
  }
  return globalForDb.__recruiterDashboardPool
}

let schemaAppliedPromise = globalForDb.__recruiterDashboardSchemaApplied || null

function readSchemaSql() {
  const schemaPath = path.join(process.cwd(), 'schema.sql')
  return fs.readFileSync(schemaPath, 'utf8')
}

async function applySchema() {
  const pool = getPool()
  const sql = readSchemaSql()
  await pool.query(sql)
}

// Ensures schema.sql has been applied at least once for this process. Safe
// to call on every request; after the first successful call it's a no-op.
export function ensureSchema() {
  if (!schemaAppliedPromise) {
    schemaAppliedPromise = applySchema().catch((err) => {
      // Allow retrying on a later request if the first attempt failed
      // (e.g. DB was briefly unreachable on cold start).
      schemaAppliedPromise = null
      throw err
    })
    globalForDb.__recruiterDashboardSchemaApplied = schemaAppliedPromise
  }
  return schemaAppliedPromise
}

export async function query(text, params) {
  await ensureSchema()
  const pool = getPool()
  return pool.query(text, params)
}
