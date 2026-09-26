import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  buildReplyRaw,
  extractPlaintext,
  normalizeSubject,
  sendReply,
} from '../lib/triage/gmail'
import { parseAddress } from '../lib/triage/email'

function decodeRaw(raw) {
  const text = Buffer.from(raw, 'base64url').toString('utf8')
  const [head, body] = text.split('\r\n\r\n')
  const headers = {}
  for (const line of head.split('\r\n')) {
    const i = line.indexOf(': ')
    headers[line.slice(0, i)] = line.slice(i + 2)
  }
  return { headers, body: Buffer.from(body.replace(/\r\n/g, ''), 'base64').toString('utf8') }
}

describe('parseAddress', () => {
  it.each([
    ['Jane Doe <jane@co.com>', { name: 'Jane Doe', address: 'jane@co.com' }],
    ['"Doe, Jane" <jane@co.com>', { name: 'Doe, Jane', address: 'jane@co.com' }],
    ['<jane@co.com>', { name: '', address: 'jane@co.com' }],
    ['jane@co.com', { name: '', address: 'jane@co.com' }],
    ['', { name: '', address: '' }],
  ])('%s', (input, expected) => {
    expect(parseAddress(input)).toEqual(expected)
  })
})

describe('normalizeSubject', () => {
  it('strips stacked and numbered Re: prefixes', () => {
    expect(normalizeSubject('RE: Re[2]:  re: Role at Acme')).toBe('Role at Acme')
    expect(normalizeSubject('Role at Acme')).toBe('Role at Acme')
    expect(normalizeSubject(null)).toBe('')
  })
})

describe('extractPlaintext', () => {
  it('finds the text/plain part in a nested multipart payload', () => {
    const payload = {
      mimeType: 'multipart/mixed',
      parts: [
        {
          mimeType: 'multipart/alternative',
          parts: [
            { mimeType: 'text/html', body: { data: Buffer.from('<p>hi</p>').toString('base64url') } },
            { mimeType: 'text/plain', body: { data: Buffer.from('héllo').toString('base64url') } },
          ],
        },
      ],
    }
    expect(extractPlaintext(payload)).toBe('héllo')
  })

  it('returns an empty string when there is no plain-text part', () => {
    expect(extractPlaintext({ mimeType: 'text/html', body: { data: 'x' } })).toBe('')
  })
})

describe('buildReplyRaw', () => {
  it('builds threading headers and a base64 UTF-8 body', () => {
    const { headers, body } = decodeRaw(
      buildReplyRaw({
        to: 'jane@co.com',
        subject: 'Re: Role',
        body: 'Thanks, café chat soon.',
        inReplyTo: '<m2@co.com>',
        references: '<m1@co.com> <m2@co.com>',
      })
    )
    expect(headers.To).toBe('jane@co.com')
    expect(headers.Subject).toBe('Re: Role')
    expect(headers['In-Reply-To']).toBe('<m2@co.com>')
    expect(headers.References).toBe('<m1@co.com> <m2@co.com>')
    expect(headers['Content-Type']).toBe('text/plain; charset="UTF-8"')
    expect(body).toBe('Thanks, café chat soon.')
  })

  it('strips CR/LF from header values so inbound text cannot inject headers', () => {
    const { headers } = decodeRaw(
      buildReplyRaw({ to: 'a@b.com\r\nBcc: evil@x.com', subject: 'Hi\nBcc: evil@x.com', body: 'x' })
    )
    expect(headers.Bcc).toBeUndefined()
    expect(headers.To).toBe('a@b.com Bcc: evil@x.com')
  })

  it('encodes a non-ASCII subject as an RFC 2047 encoded-word', () => {
    const { headers } = decodeRaw(buildReplyRaw({ to: 'a@b.com', subject: 'Re: Café role', body: 'x' }))
    expect(headers.Subject).toBe(`=?UTF-8?B?${Buffer.from('Re: Café role').toString('base64')}?=`)
  })

  it('omits threading headers when there are none', () => {
    const { headers } = decodeRaw(buildReplyRaw({ to: 'a@b.com', subject: 'S', body: 'x' }))
    expect(headers['In-Reply-To']).toBeUndefined()
    expect(headers.References).toBeUndefined()
  })
})

describe('sendReply', () => {
  let calls
  let modifyFails

  beforeEach(() => {
    process.env.GMAIL_CLIENT_ID = 'id'
    process.env.GMAIL_CLIENT_SECRET = 'secret'
    process.env.GMAIL_REFRESH_TOKEN = 'refresh'
    globalThis.__gmailAccessToken = undefined
    calls = []
    modifyFails = false
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init = {}) => {
      const body = init.body && typeof init.body === 'string' ? JSON.parse(init.body) : null
      calls.push({ url: String(url), method: init.method || 'GET', body })
      const json = (data, status = 200) => new Response(JSON.stringify(data), { status })
      if (String(url).startsWith('https://oauth2')) return json({ access_token: 'tok', expires_in: 3600 })
      if (String(url).includes('format=metadata')) {
        return json({
          messages: [
            {
              payload: {
                headers: [
                  { name: 'Message-ID', value: '<m2@co.com>' },
                  { name: 'References', value: '<m1@co.com>' },
                  { name: 'Subject', value: 'Staff Engineer at Acme' },
                ],
              },
            },
          ],
        })
      }
      if (String(url).endsWith('/messages/send')) return json({ id: 'sent-1' })
      if (String(url).endsWith('/modify')) return modifyFails ? json({}, 500) : json({})
      return json({}, 404)
    })
  })

  afterEach(() => vi.restoreAllMocks())

  it('threads the reply and falls back to the thread subject when the draft drifted', async () => {
    const id = await sendReply('t1', 'jane@co.com', 'Re: Something else', 'Thanks.')
    expect(id).toBe('sent-1')

    const send = calls.find((c) => c.url.endsWith('/messages/send'))
    expect(send.body.threadId).toBe('t1')
    const { headers } = decodeRaw(send.body.raw)
    expect(headers.Subject).toBe('Re: Staff Engineer at Acme')
    expect(headers['In-Reply-To']).toBe('<m2@co.com>')
    expect(headers.References).toBe('<m1@co.com> <m2@co.com>')

    const modify = calls.find((c) => c.url.endsWith('/modify'))
    expect(modify.body).toEqual({ removeLabelIds: ['UNREAD'] })
  })

  it('keeps the drafted subject when it already matches the thread', async () => {
    await sendReply('t1', 'jane@co.com', 'RE: Staff Engineer at Acme', 'Thanks.')
    const send = calls.find((c) => c.url.endsWith('/messages/send'))
    expect(decodeRaw(send.body.raw).headers.Subject).toBe('RE: Staff Engineer at Acme')
  })

  it('does not fail the send when marking the thread read fails', async () => {
    modifyFails = true
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    await expect(sendReply('t1', 'jane@co.com', 'Re: x', 'Thanks.')).resolves.toBe('sent-1')
  })
})
