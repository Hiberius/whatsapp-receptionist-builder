# Data protection

Written for the European market, where a receptionist processes health hints, addresses
and phone numbers as a matter of routine.

## Minimise at the boundary

The webhook payload contains more than you need. Store what the booking requires and
drop the rest rather than keeping the raw payload forever "just in case". A raw-payload
table is the single largest liability in this kind of system, and the least examined.

Keep raw payloads only for as long as replay debugging needs them, and put a retention
job on that table like any other.

## PII must not reach the logs

Redact at the logger, not at each call site. One redaction list, applied centrally:
phone numbers, email addresses, full names, addresses, fiscal codes, VAT numbers, IBANs,
tokens and API keys, and the message body itself.

Logging the message body is the most common leak, and it is also the least useful log
line in production: the message id plus the intent tells you what you need.

## Retention

Publish a retention policy and then enforce it in code, with a scheduled job. Two rules
that keep it honest:

- The thresholds live in one place and the privacy text reads them, or a test fails when
  the code and the policy diverge.
- The job has a dry-run mode. A deletion job nobody has ever watched run is a deletion
  job nobody trusts, so it never gets enabled.

## Access and erasure

- **Article 15, access.** Export everything you hold about one contact: conversations,
  appointments, consent records. It must be exportable while the contact is still active.
- **Article 17, erasure.** Delete or irreversibly anonymise. Consider what an appointment
  row means after the customer is erased: usually you keep the slot and the invoice, with
  the person removed.
- Write both to an audit log. Being able to show when a request arrived and when it was
  satisfied is the point of the audit log.

## Consent

The customer starting the conversation is the lawful basis for answering it. It is not
consent to send them marketing later. Keep the two separate, record which one you have,
and check it in the outbox before any non-service message.

## Multi-tenant isolation

The failure mode is one tenant reading another's conversations, and it is the one users
will never forgive.

- Row Level Security on every table that holds tenant data.
- A service-role client bypasses RLS, so any server module using it depends on hand
  written `tenant_id` filters. Cover those with tests that fail when a filter is deleted.
- Exercise the policies themselves against a real database in CI. Filter tests prove the
  code is careful; only a policy test proves the database is safe.
- Resolve the WhatsApp number to a tenant at send time, and make a number unclaimable by
  a second tenant at the schema level.

## Credentials

- Encrypt per-tenant API keys and OAuth tokens at rest, with authenticated encryption.
- The key belongs in a secret manager, not next to the ciphertext.
- Rotate on tenant offboarding, and revoke the OAuth grant rather than only deleting the
  row.
