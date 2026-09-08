# Booking correctness

## Double booking is a race

Two customers ask for Thursday 15:00 within the same second. Both requests read the slot
as free, both write. Every application-level check loses this race, including one wrapped
in a transaction that only reads.

The database has to be the one saying no:

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE appointments ADD CONSTRAINT no_overlap
  EXCLUDE USING gist (
    resource_id WITH =,
    tstzrange(starts_at, ends_at) WITH &&
  ) WHERE (status <> 'cancelled');
```

`resource_id` is whatever cannot be in two places at once: the practitioner, the room,
the chair. If you have several, the constraint goes on the one that is scarce.

Then handle the violation as a normal path, not a 500: catch it, apologise, offer the
next free slot. Under real load this fires regularly and the customer should never see
a stack trace.

## Availability

Availability is a subtraction, in this order:

```
opening hours for that weekday
  - closures and holidays
  - existing appointments
  - buffers before and after each appointment
  - the lead time you need before a booking (no bookings in 20 minutes)
  = bookable slots
```

Two details people skip:

- **Buffers belong to the service, not the business.** A 20-minute consultation and a
  two-hour treatment do not need the same gap after them.
- **Slot granularity is not service duration.** Offering 15-minute starts for a 60-minute
  service fills the calendar with unusable gaps. Align starts to the granularity that
  keeps the day packable.

## Timezones

- Store `timestamptz`. Always.
- Compute opening hours in the **tenant's** timezone, not the server's and not the
  customer's.
- Display in the customer's timezone only if you actually know it. Guessing from a phone
  prefix is wrong for anyone travelling or holding a foreign SIM.
- On a DST boundary, a 30-minute slot is not always 30 minutes of wall clock, and a day
  is not always 24 hours. Generate slots from the local calendar, then convert, never
  the other way round.
- A recurring appointment stored as an offset breaks at the next DST change. Store the
  local rule and expand it.

## Confirmations, reminders, cancellations

- **Confirmation** goes out inside the 24-hour window, so it can be free-form.
- **Reminders** are always outside the window. They must be approved templates. Decide the
  timing per service: a same-day reminder for a haircut, 24 hours plus 2 hours for
  something with a real no-show cost.
- **Cancellation and rescheduling** must be possible from the same conversation, or the
  cancellations arrive as no-shows instead.
- Every state change writes to the calendar and to your own table. If the calendar is the
  only record, an API outage erases your business.

## Talking to Google Calendar

- OAuth refresh tokens expire on password change, revocation and inactivity. Detect the
  failure, mark the connection broken, and tell the tenant. A silent sync failure is the
  worst possible outcome: the assistant keeps booking into a calendar nobody sees.
- Use the free/busy query for availability, not a full event list, and keep your own
  table as the source of truth for what **you** booked.
- Send an idempotency key on create, or a retry after a timeout produces two events.
- The tenant will also create events by hand. Treat the external calendar as authoritative
  for busy time and your own table as authoritative for your appointments; reconcile on a
  schedule rather than assuming.

## Extraction from natural language

"Giovedì pomeriggio" is not a timestamp. What the extractor returns must be validated,
never trusted:

- Resolve relative dates against the tenant's timezone and today's date, not the model's
  idea of today.
- A date in the past means the customer meant next week; ask rather than booking.
- Ambiguity gets one clarifying question, then a proposed slot. Two questions in a row
  and people leave.
- Never book without an explicit confirmation of the exact slot in the customer's own
  words or a tap on a confirm button.
