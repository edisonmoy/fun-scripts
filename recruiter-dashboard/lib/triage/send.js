import { parseAddress } from './email'
import { sendReply } from './gmail'
import { claimForSend, releaseSendClaim } from './records'

export class NotSendableError extends Error {}

// Sends a drafted row's reply right away. Claims the row (drafted -> sent)
// before sending so only one request can ever send it; a failed send
// releases the claim so the row returns to drafted and can be retried.
export async function sendDraft(id) {
  const record = await claimForSend(id)
  if (!record) throw new NotSendableError('This reply was already sent or has no draft.')

  try {
    await sendReply(
      record.gmail_thread_id,
      parseAddress(record.sender).address,
      record.draft_subject,
      record.draft_body
    )
  } catch (err) {
    console.error(`record_id=${id} failed to send: ${err.message}`)
    await releaseSendClaim(id)
    throw err
  }
  return record
}
