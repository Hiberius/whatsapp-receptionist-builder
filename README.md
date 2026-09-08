# WhatsApp Receptionist Builder

**An Agent Skill for building an AI receptionist on the WhatsApp Cloud API: one that
answers customers, books real appointments, and does not send the same reply twice.
The four traps that break every first implementation, plus offline tooling for the two
you cannot test without a phone.**

[![License: MIT](https://img.shields.io/badge/License-MIT-2ea44f.svg)](LICENSE)
![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-3776AB?logo=python&logoColor=white)
![Zero dependencies](https://img.shields.io/badge/dependencies-0-6E56CF)
![WhatsApp Cloud API](https://img.shields.io/badge/WhatsApp-Cloud%20API-25D366?logo=whatsapp&logoColor=white)

```bash
npx skills add Hiberius/whatsapp-receptionist-builder
```

Works with Claude Code, Claude Desktop, Codex, Cursor, Windsurf, OpenClaw and anything
else that reads a `SKILL.md`.

---

## The four traps

**1. The signature is over the raw body.** Parse the JSON before verifying and the digest
never matches. It presents as a wrong secret, and it is not.

**2. The 24-hour window closes on the customer's last message.** Your replies do not
extend it. Every reminder and follow-up you send on a schedule is outside it by
definition, so it must be a template approved in advance.

**3. Meta retries.** On timeouts too. Without an idempotency table on the message id, one
customer gets two answers and, if the first one booked, two appointments.

**4. Double booking is a race.** Two requests read the same free slot in the same
millisecond. No application-level check wins that; a database exclusion constraint does.

## Tools that work without a phone number

```bash
# is the window open, and how long do I have?
python3 scripts/wa.py window --last-inbound 2026-09-08T09:12:00Z
```
```
window closes  2026-09-09T09:12:00+00:00
state          OPEN
remaining      18h 12m
you may send   free-form
```

```bash
# realistic webhook bodies: text, voice note, image, button, delivery status
python3 scripts/wa.py payload audio --from 393331234567 > voice.json

# and the matching signature, so your handler sees exactly what Meta sends
curl -X POST localhost:3000/api/webhook/whatsapp \
  -H "X-Hub-Signature-256: $(python3 scripts/wa.py signature --secret "$APP_SECRET" --body-file voice.json)" \
  --data-binary @voice.json
```

Send the same payload twice with `--id wamid.SAME` and you have an idempotency test.

## The shape that works

```
Meta webhook ──► verify signature on the RAW body
             ──► record the message id, drop it if already seen
             ──► enqueue ──► return 200          (under 1 second)

worker       ──► intent ──► real availability ──► book ──► enqueue the reply
outbox       ──► FOR UPDATE SKIP LOCKED ──► send ──► backoff ──► dead letter + alert
```

Calling the model inside the webhook handler is the mistake everything else follows from.

## Documentation

- [`SKILL.md`](SKILL.md) — the skill itself, what the agent reads
- [`references/architecture.md`](references/architecture.md) — webhook, idempotency, outbox, retries, escalation, what to monitor
- [`references/whatsapp-api-traps.md`](references/whatsapp-api-traps.md) — the window, templates, media ids, opt-out, quality rating, delivery statuses
- [`references/booking-correctness.md`](references/booking-correctness.md) — the exclusion constraint, availability subtraction, timezones and DST, Google Calendar
- [`references/gdpr-and-data.md`](references/gdpr-and-data.md) — retention, PII redaction, Art. 15 and 17, tenant isolation, credentials

## A working implementation

[whatsapp-receptionist](https://github.com/Hiberius/whatsapp-receptionist) is the full
thing: Next.js, Supabase, multi-tenant, GDPR-first, 544 unit tests and 56 E2E tests, MIT.
This skill is the reasoning behind it, usable on any stack.

## Not for

Marketing broadcasts, unofficial WhatsApp clients, or scraping. Those get numbers banned.
The Cloud API is the only path that survives contact with a real business.

## License

MIT. No network calls, no telemetry, no dependencies.
