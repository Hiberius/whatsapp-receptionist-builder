---
name: whatsapp-receptionist-builder
description: Use when building, extending or debugging an AI assistant on WhatsApp that answers customers and books appointments - a receptionist, booking bot or support agent on the WhatsApp Cloud API. Covers webhook signature failures, the 24-hour customer service window, duplicate replies from webhook retries, double-booking under concurrency, voice note handling, human escalation and multi-tenant number routing.
---

# WhatsApp Receptionist Builder

## Overview

A receptionist on WhatsApp is not a chatbot with a calendar bolted on. It is a webhook
that must answer in milliseconds, a queue that must not send the same message twice, a
booking that must not double-book under concurrency, and a messaging window that closes
24 hours after the customer's last message whether you are ready or not.

**Core principle: the webhook acknowledges, the worker thinks.** Everything else in this
skill follows from that one decision.

## When to use

- Building an AI receptionist, booking assistant or support agent on the WhatsApp Cloud API
- Webhook returns 200 but Meta keeps retrying, or the customer receives the same reply twice
- Signature verification fails and the secret is definitely correct
- Messages send fine during a conversation and get rejected hours later
- Two customers hold the same slot
- Voice notes arrive and nothing happens
- Routing several business numbers into one deployment

**Not for:** WhatsApp marketing broadcasts, unofficial or reverse-engineered WhatsApp
clients, or scraping. Those get numbers banned; the Cloud API is the only path that
survives contact with a real business.

A complete, working implementation of everything described here is
[whatsapp-receptionist](https://github.com/Hiberius/whatsapp-receptionist) (Next.js,
Supabase, MIT).

## The shape that works

```
Meta webhook ──► verify signature on the RAW body
             ──► record the message id, drop it if already seen
             ──► enqueue
             ──► return 200            (target: under 1 second)

worker       ──► classify intent ──► check real availability ──► book
             ──► enqueue the reply

outbox       ──► claim FOR UPDATE SKIP LOCKED ──► send ──► retry with backoff
             ──► dead letter after N attempts
```

Doing the LLM call inside the webhook handler is the single most common architecture
mistake. Meta times out and retries; the retry runs the whole pipeline again; the
customer gets two answers and, if the first one booked, two appointments.

## The four traps, in the order they will hit you

**1. Signature over the raw body.** `X-Hub-Signature-256` is HMAC-SHA256 of the exact
bytes Meta sent. Parse the JSON and re-serialise it and the digest no longer matches,
which presents as "wrong secret" and is not. Read the raw body first, verify, then parse.
Compare in constant time.

```bash
python3 scripts/wa.py signature --secret "$APP_SECRET" --body-file captured.json --verify "sha256=..."
```

**2. The 24-hour customer service window.** Free-form messages are only allowed within
24 hours of the customer's **last inbound message**. Your own replies do not extend it.
Outside the window only an approved template goes through, and the customer's reply to
that template opens a new window. Reminders, follow-ups and "your appointment is
tomorrow" all live outside the window by definition, so they must be templates approved
in advance.

```bash
python3 scripts/wa.py window --last-inbound 2026-09-08T09:12:00Z
```

**3. Retries are guaranteed, so idempotency is mandatory.** Meta redelivers on any
non-2xx and on timeouts. Store every `wamid` in a table with a unique constraint and
make a duplicate a no-op **before** any side effect. The same applies to your outbound
sends: one message id, one send.

**4. Double booking is a race, not a bug in your availability check.** Two requests read
the same free slot in the same millisecond and both write. Application-level checks
cannot fix this. The database must refuse it:

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE appointments ADD CONSTRAINT no_overlap
  EXCLUDE USING gist (
    resource_id WITH =,
    tstzrange(starts_at, ends_at) WITH &&
  ) WHERE (status <> 'cancelled');
```

Then treat the constraint violation as a normal outcome: apologise, offer the next slot.

## Test locally without a phone

```bash
python3 scripts/wa.py payload text  --from 393331234567 > text.json
python3 scripts/wa.py payload audio --from 393331234567 > voice.json
python3 scripts/wa.py payload status --id wamid.SAME  # delivery receipt
python3 scripts/wa.py payload text --id wamid.SAME    # send twice: idempotency test

curl -X POST localhost:3000/api/webhook/whatsapp \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: $(python3 scripts/wa.py signature --secret "$APP_SECRET" --body-file text.json)" \
  --data-binary @text.json
```

`--data-binary` matters: `-d` mangles newlines and the signature stops matching.

## Reference

| Topic | File |
|---|---|
| Queue, worker, outbox, retries, dead letter | `references/architecture.md` |
| Cloud API behaviour: templates, media, opt-out, quality rating, phone formats | `references/whatsapp-api-traps.md` |
| Availability, timezones, DST, buffers, reminders, cancellation | `references/booking-correctness.md` |
| Retention, PII in logs, Art. 15 and 17, tenant isolation | `references/gdpr-and-data.md` |

## Common mistakes

- **Calling the model inside the webhook.** See above. Everything downstream breaks.
- **Trusting `messages[0]`.** A payload can carry several messages, and status callbacks
  carry none. Iterate, and branch on `statuses` versus `messages`.
- **Treating a delivery status as a customer message.** It has no `from` and no body, and
  handlers that assume otherwise crash on every receipt.
- **Storing local times.** Store `timestamptz`, compute business hours in the tenant's
  zone, and remember that a 30-minute slot on a DST night is not 30 minutes of wall clock.
- **Silently dropping a voice note that failed to transcribe.** Say you could not hear it
  and ask them to type. Silence reads as a broken number.
- **No human escalation path.** Every receptionist meets a case it must not handle. Flip
  the conversation state, notify a person, and tell the customer someone is coming.
- **One shared API credential across tenants.** Resolve the number to the tenant at send
  time, encrypt per-tenant credentials at rest, and make a number unclaimable twice.
