# WhatsApp Cloud API behaviour

## The 24-hour customer service window

Free-form messages are permitted only within 24 hours of the customer's **last inbound
message**. Precise consequences:

- Your outbound messages do **not** extend the window.
- The clock starts at the customer's message, not at the conversation's creation.
- Outside the window only an approved **template** is accepted. Everything else is
  rejected by the API.
- The customer's reply to a template opens a fresh 24-hour window.

Therefore every message your system sends on its own schedule must be a template
approved in advance: appointment reminders, follow-ups, "we are back in the office",
waiting-list notifications. Get them approved before you need them; approval is not
instant and a rejected template on the morning of a launch stops the whole flow.

```bash
python3 scripts/wa.py window --last-inbound 2026-09-08T09:12:00Z
```

## Templates

- Approved per language and per category. Marketing, utility and authentication are
  priced and treated differently.
- Variables are positional (`{{1}}`, `{{2}}`). Sending the wrong count is a hard error.
- Editing an approved template sends it back for review.
- A template with a low read rate or high block rate degrades your **quality rating**,
  and a degraded rating lowers your messaging limit. Reminders that nobody wants cost
  you throughput on messages people do want.

## Media

Inbound media arrives as an **id**, not a URL. Two calls: resolve the id to a temporary
URL, then download it with the same bearer token. The URL expires quickly, so download
at receipt rather than at processing time.

Voice notes arrive as `audio/ogg; codecs=opus` with `voice: true`. Transcribe, and when
transcription fails, say so and ask the customer to type. Silence after a voice note is
indistinguishable from a dead number.

Size limits differ by type and change; read the current documentation rather than
hardcoding an assumption, and handle the rejection path.

## Opt-out

A customer who asks to stop must stop receiving messages, and the request arrives in
free text as often as through a button. Keep an opt-out flag on the contact, check it in
the outbox before every send, and record who set it and when. This is both a policy
requirement and the fastest way to protect your quality rating.

## Phone numbers

Store E.164 without the `+` for the API, and normalise on the way in. The same customer
writing from a roaming SIM or with a leading zero must resolve to one contact, or your
conversation history splits in two and the assistant loses the thread.

## Statuses

Delivery receipts arrive on the same webhook under `statuses`, not `messages`. They have
no `from` and no body. A handler that assumes every payload is a customer message crashes
on the first receipt, which arrives seconds after your first send.

States: `sent`, `delivered`, `read`, `failed`. Only `failed` needs action, and its error
code tells you which action.

## Rate limits and quality

- Messaging limits scale with quality rating and business verification.
- A rating drop is usually caused by blocks and by messages the customer did not expect.
- Throughput limits apply per number; a burst of reminders can starve live conversations.
  Give live replies a higher priority in the outbox than scheduled sends.

## Testing

The test number Meta provides can only message a short allowlist and behaves differently
from a production number under load. Verify the full path on a real number before a
launch, including a message sent outside the 24-hour window, which is the case that
never gets tested and always breaks first.
