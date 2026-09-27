import { NextResponse } from 'next/server'
import { NotSendableError, sendDraft } from '../../../../../lib/triage/send'

export async function POST(request, context) {
  const { id } = await context.params
  if (!/^\d+$/.test(id)) {
    return NextResponse.json({ error: 'invalid id' }, { status: 400 })
  }

  try {
    await sendDraft(Number(id))
    return NextResponse.json({ ok: true })
  } catch (err) {
    if (err instanceof NotSendableError) {
      return NextResponse.json({ error: err.message }, { status: 409 })
    }
    return NextResponse.json({ error: 'Sending failed. Try again.' }, { status: 502 })
  }
}
