// Minimal Gmail REST client (plain fetch, no googleapis dependency) for the
// handful of calls triage needs. Authenticates with a long-lived OAuth
// refresh token - see scripts/authorize_gmail.py for how to mint one.

const TOKEN_URL = 'https://oauth2.googleapis.com/token'
const API_BASE = 'https://gmail.googleapis.com/gmail/v1/users/me'

const globalForGmail = globalThis

async function getAccessToken() {
  const cached = globalForGmail.__gmailAccessToken
  // Refresh a minute early so a token can't expire mid-request.
  if (cached && cached.expiresAt - 60_000 > Date.now()) return cached.token

  for (const name of ['GMAIL_CLIENT_ID', 'GMAIL_CLIENT_SECRET', 'GMAIL_REFRESH_TOKEN']) {
    if (!process.env[name]) throw new Error(`${name} is not set`)
  }
  const res = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: process.env.GMAIL_CLIENT_ID,
      client_secret: process.env.GMAIL_CLIENT_SECRET,
      refresh_token: process.env.GMAIL_REFRESH_TOKEN,
    }),
  })
  if (!res.ok) throw new Error(`Gmail token refresh failed (${res.status})`)
  const data = await res.json()
  globalForGmail.__gmailAccessToken = {
    token: data.access_token,
    expiresAt: Date.now() + data.expires_in * 1000,
  }
  return data.access_token
}

async function gmail(path, { method = 'GET', body } = {}) {
  const token = await getAccessToken()
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    // Status only - response bodies can echo request content.
    throw new Error(`Gmail ${method} ${path.split('?')[0]} failed (${res.status})`)
  }
  return res.json()
}

// Gmail's `after:` operator is date-granularity only (no time-of-day), so
// this can re-surface threads from earlier the same day as the last sync -
// the caller dedupes against triage_records.
export async function searchCandidateThreads(query, afterDate) {
  const y = afterDate.getUTCFullYear()
  const m = afterDate.getUTCMonth() + 1
  const d = afterDate.getUTCDate()
  const q = `${query} after:${y}/${m}/${d}`

  const ids = []
  let pageToken
  do {
    const params = new URLSearchParams({ q })
    if (pageToken) params.set('pageToken', pageToken)
    const data = await gmail(`/threads?${params}`)
    for (const t of data.threads || []) ids.push(t.id)
    pageToken = data.nextPageToken
  } while (pageToken)
  return ids
}

function headerMap(message) {
  const map = {}
  for (const h of message?.payload?.headers || []) map[h.name.toLowerCase()] = h.value
  return map
}

export function extractPlaintext(payload) {
  if (!payload) return ''
  if (payload.mimeType === 'text/plain' && payload.body?.data) {
    return Buffer.from(payload.body.data, 'base64url').toString('utf8')
  }
  for (const part of payload.parts || []) {
    const text = extractPlaintext(part)
    if (text) return text
  }
  return ''
}

// Returns the most recent message's {sender, subject, receivedAt, body}.
export async function getThreadPlaintext(threadId) {
  const thread = await gmail(`/threads/${encodeURIComponent(threadId)}?format=full`)
  const messages = thread.messages || []
  if (messages.length === 0) return { sender: '', subject: '', receivedAt: null, body: '' }

  const message = messages[messages.length - 1]
  const headers = headerMap(message)
  const parsed = headers.date ? new Date(headers.date) : null
  return {
    sender: headers.from || '',
    subject: headers.subject || '',
    receivedAt: parsed && !Number.isNaN(parsed.getTime()) ? parsed : null,
    body: extractPlaintext(message.payload),
  }
}

// Returns the id of the Gmail label `name`, creating it if it doesn't exist.
export async function ensureLabel(name) {
  const { labels = [] } = await gmail('/labels')
  const existing = labels.find((l) => l.name === name)
  if (existing) return existing.id
  const created = await gmail('/labels', {
    method: 'POST',
    body: { name, labelListVisibility: 'labelShow', messageListVisibility: 'show' },
  })
  return created.id
}

export async function applyLabel(threadId, labelId) {
  await gmail(`/threads/${encodeURIComponent(threadId)}/modify`, {
    method: 'POST',
    body: { addLabelIds: [labelId] },
  })
}

// Strip any leading Re:/RE:/Re[2]: prefixes, for comparing a drafted subject
// against the thread's own subject.
export function normalizeSubject(subject) {
  return (subject || '').replace(/^\s*(re\s*(\[\d+\])?\s*:\s*)+/i, '').trim()
}

// Headers needed to make a reply thread correctly in the RECIPIENT's mail
// client, not just Edison's Gmail. Gmail's threadId only files the sent
// message into Edison's own copy of the thread; the recruiter's client
// (Outlook, Superhuman, another Gmail account) threads on RFC 5322
// In-Reply-To/References, so without them the reply lands as a standalone
// message and the recruiter's response starts a brand new thread.
async function getThreadReplyHeaders(threadId) {
  const params = new URLSearchParams({ format: 'metadata' })
  for (const h of ['Message-ID', 'References', 'Subject']) params.append('metadataHeaders', h)
  const thread = await gmail(`/threads/${encodeURIComponent(threadId)}?${params}`)
  const messages = thread.messages || []
  if (messages.length === 0) return { messageId: '', references: '', subject: '' }

  const headers = headerMap(messages[messages.length - 1])
  const messageId = headers['message-id'] || ''
  // References is the full ancestry chain: everything the message we're
  // replying to already referenced, plus that message itself.
  const references = [headers.references, messageId].filter(Boolean).join(' ')
  return { messageId, references, subject: headers.subject || '' }
}

// Header values here come from inbound email (sender, subject), so strip
// CR/LF to rule out header injection into the outgoing message.
function headerValue(value) {
  return String(value).replace(/[\r\n]+/g, ' ')
}

function encodeHeaderText(value) {
  const clean = headerValue(value)
  // RFC 2047 encoded-word for anything outside printable ASCII.
  if (/^[\x20-\x7e]*$/.test(clean)) return clean
  return `=?UTF-8?B?${Buffer.from(clean, 'utf8').toString('base64')}?=`
}

// Builds the base64url-encoded RFC 5322 message Gmail's send endpoint takes.
export function buildReplyRaw({ to, subject, body, inReplyTo, references }) {
  const lines = [
    `To: ${headerValue(to)}`,
    `Subject: ${encodeHeaderText(subject)}`,
  ]
  if (inReplyTo) lines.push(`In-Reply-To: ${headerValue(inReplyTo)}`)
  if (references) lines.push(`References: ${headerValue(references)}`)
  lines.push(
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset="UTF-8"',
    'Content-Transfer-Encoding: base64',
    '',
    Buffer.from(body, 'utf8').toString('base64').replace(/.{76}/g, '$&\r\n')
  )
  return Buffer.from(lines.join('\r\n'), 'utf8').toString('base64url')
}

// Sends `body` as a reply within `threadId`. Returns the sent message id.
export async function sendReply(threadId, to, subject, body) {
  const reply = await getThreadReplyHeaders(threadId)

  // The drafted subject is model- or template-generated, so it can drift
  // from the thread's actual subject. Gmail needs them to match (modulo the
  // Re: prefix) to keep the message in the thread, and so does every other
  // client's subject-based threading fallback, so the thread's own subject
  // wins whenever they differ.
  let finalSubject = subject
  if (reply.subject && normalizeSubject(subject) !== normalizeSubject(reply.subject)) {
    finalSubject = `Re: ${normalizeSubject(reply.subject)}`
  }

  const raw = buildReplyRaw({
    to,
    subject: finalSubject,
    body,
    inReplyTo: reply.messageId,
    references: reply.references,
  })
  const sent = await gmail('/messages/send', { method: 'POST', body: { raw, threadId } })

  // Edison has now replied, so the thread shouldn't linger as unread.
  // Best-effort: the reply is already out, and surfacing this as a failed
  // send would invite sending it a second time.
  try {
    await gmail(`/threads/${encodeURIComponent(threadId)}/modify`, {
      method: 'POST',
      body: { removeLabelIds: ['UNREAD'] },
    })
  } catch (err) {
    console.warn(`thread_id=${threadId} sent reply but failed to mark thread read: ${err.message}`)
  }

  return sent.id
}
