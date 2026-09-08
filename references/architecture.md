# Architecture

## Three moving parts, on purpose

```
webhook   accept, verify, deduplicate, enqueue, return 200
worker    understand, decide, act, enqueue a reply
outbox    send, retry, give up loudly
```

Each one fails differently and must be able to fail without taking the others down. A
model outage should leave messages queued, not lost. A send failure should retry, not
re-run the model.

## Webhook

Budget: under one second, and it should usually be under 100ms.

```
1. read the RAW body                      (bytes, before any parsing)
2. verify X-Hub-Signature-256             (constant time; reject with 401)
3. parse
4. for each entry.changes[].value:
     - statuses[]  -> record delivery state, done
     - messages[]  -> INSERT the wamid; on conflict, return 200 and stop
                   -> enqueue
5. return 200
```

Returning non-2xx makes Meta redeliver. Returning 200 after a crash loses the message.
So: persist first, work later. The enqueue must be in the same transaction as the
idempotency insert, or a crash between them loses exactly the messages you thought you
had accepted.

## Idempotency

```sql
CREATE TABLE webhook_events (
  id          text PRIMARY KEY,      -- the wamid, or the status id
  received_at timestamptz NOT NULL DEFAULT now(),
  payload     jsonb NOT NULL
);
```

`INSERT ... ON CONFLICT DO NOTHING` and check the row count. Zero rows means a replay:
return 200 and do nothing else. This one table removes an entire class of duplicate
bookings and duplicate replies.

Meta redelivers on timeouts too, so a slow handler that eventually succeeds still
produces duplicates without this.

## Outbox

Never call the send API from the request that decided to send. Write the intent, let a
worker drain it.

```sql
CREATE TABLE outbox (
  id            uuid PRIMARY KEY,
  tenant_id     uuid NOT NULL,
  to_number     text NOT NULL,
  body          jsonb NOT NULL,
  status        text NOT NULL DEFAULT 'pending',  -- pending|sent|failed|dead
  attempts      int  NOT NULL DEFAULT 0,
  next_retry_at timestamptz NOT NULL DEFAULT now(),
  last_error    text
);
```

Claiming work, safely, with several workers running:

```sql
UPDATE outbox SET status = 'sending', attempts = attempts + 1
WHERE id IN (
  SELECT id FROM outbox
  WHERE status = 'pending' AND next_retry_at <= now()
  ORDER BY next_retry_at
  FOR UPDATE SKIP LOCKED
  LIMIT 20
)
RETURNING *;
```

`FOR UPDATE SKIP LOCKED` is what makes two workers safe. Without it they either block on
each other or send the same message twice.

Backoff: `next_retry_at = now() + interval '1 minute' * power(2, attempts)`, capped.
After ~6 attempts move to `dead` and alert a human. A dead-letter row nobody looks at is
the same as a lost message, so the alert is part of the design, not an extra.

## Worker

```
load conversation context (bounded: last N turns, plus the tenant's knowledge base)
classify intent
  booking   -> extract service, date, time, contact -> check availability -> book
  question  -> answer from the knowledge base, refuse to invent
  escalate  -> flip state, notify a human, tell the customer
compose reply -> enqueue to outbox
```

Two guardrails worth building on day one:

- **Never invent availability, prices or policies.** If the answer is not in the tenant's
  data, escalate. A receptionist that confidently invents an opening hour costs more than
  one that says "let me check with someone".
- **Bound the context.** Conversations with regulars grow without limit. Cap the turns and
  summarise older history, or the token cost per message grows quietly for months.

## Escalation

Escalation is a state change on the conversation, not a message. Three things must
happen together:

1. the conversation stops being answered automatically
2. a person is notified with the context and a link that opens the thread
3. the customer is told a person is coming

Skip the third and the customer repeats themselves into silence.

## Observability that earns its place

- Queue depth and oldest pending age. A queue that stops draining is the failure that
  looks like nothing at all.
- Dead letters, with an alert.
- Time from inbound to reply, at the 95th percentile.
- Send failures by error code: the Cloud API's codes distinguish "outside the window"
  from "number not on WhatsApp" from "template not approved", and they need different
  fixes.
