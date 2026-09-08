#!/usr/bin/env python3
"""wa - WhatsApp Cloud API build helpers.

The three things that go wrong first when you build a receptionist on WhatsApp:
the webhook signature, the 24-hour service window, and having nothing realistic
to test the handler with. This covers all three, offline.

  wa.py signature --secret S --body-file payload.json      compute X-Hub-Signature-256
  wa.py signature --secret S --body-file p.json --verify sha256=...   check one
  wa.py window --last-inbound 2026-09-08T09:12:00Z         free-form or template?
  wa.py payload text --from 393331234567                   realistic webhook body
  wa.py payload audio --from 393331234567 > voice.json

Pure standard library, Python 3.8+. No network, no dependencies.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import sys
import uuid

SERVICE_WINDOW_HOURS = 24


# --------------------------------------------------------------------------
# webhook signature
# --------------------------------------------------------------------------

def sign(secret, raw_body):
    """X-Hub-Signature-256 exactly as Meta computes it: HMAC-SHA256 over the RAW body.

    The raw bytes matter. Parsing the JSON and re-serialising it changes key order and
    whitespace, the digest stops matching, and every webhook is rejected with a 401 that
    looks like a wrong secret.
    """
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return "sha256=" + digest


def verify(secret, raw_body, header_value):
    """Constant-time comparison. A plain == leaks the digest one byte at a time."""
    expected = sign(secret, raw_body)
    return hmac.compare_digest(expected, (header_value or "").strip())


# --------------------------------------------------------------------------
# 24-hour customer service window
# --------------------------------------------------------------------------

def parse_iso(value):
    v = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(v)
    except ValueError:
        raise SystemExit("error: %r is not an ISO 8601 timestamp" % value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def window_state(last_inbound, now=None):
    """Inside the window you may send free-form. Outside it, only an approved template.

    The window is measured from the customer's last INBOUND message, not from your last
    outbound one and not from the conversation's creation. Replying does not extend it.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    closes = last_inbound + dt.timedelta(hours=SERVICE_WINDOW_HOURS)
    remaining = closes - now
    open_ = remaining.total_seconds() > 0
    return {
        "last_inbound": last_inbound.isoformat(),
        "now": now.isoformat(),
        "window_closes": closes.isoformat(),
        "open": open_,
        "remaining_seconds": max(0, int(remaining.total_seconds())),
        "may_send": "free-form" if open_ else "approved template only",
        "note": ("Free-form messages are allowed until the window closes."
                 if open_ else
                 "Free-form sends will be rejected. Use an approved template; the "
                 "customer's reply to it opens a new 24-hour window."),
    }


# --------------------------------------------------------------------------
# realistic webhook payloads
# --------------------------------------------------------------------------

def _envelope(phone_number_id, value_extra):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "102290129340398",
            "changes": [{
                "field": "messages",
                "value": dict({
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "15550001111",
                        "phone_number_id": phone_number_id,
                    },
                }, **value_extra),
            }],
        }],
    }


def payload(kind, sender, phone_number_id, text, message_id=None):
    wamid = message_id or ("wamid.TEST%s" % uuid.uuid4().hex[:22].upper())
    ts = str(int(dt.datetime.now(dt.timezone.utc).timestamp()))
    contacts = [{"profile": {"name": "Test Customer"}, "wa_id": sender}]

    if kind == "text":
        msg = {"from": sender, "id": wamid, "timestamp": ts,
               "type": "text", "text": {"body": text}}
    elif kind == "audio":
        msg = {"from": sender, "id": wamid, "timestamp": ts, "type": "audio",
               "audio": {"id": "media.%s" % uuid.uuid4().hex[:16],
                         "mime_type": "audio/ogg; codecs=opus", "voice": True}}
    elif kind == "image":
        msg = {"from": sender, "id": wamid, "timestamp": ts, "type": "image",
               "image": {"id": "media.%s" % uuid.uuid4().hex[:16],
                         "mime_type": "image/jpeg", "sha256": "b64hash",
                         "caption": text}}
    elif kind == "button":
        msg = {"from": sender, "id": wamid, "timestamp": ts, "type": "button",
               "button": {"payload": "STOP", "text": "Stop messages"}}
    elif kind == "status":
        return _envelope(phone_number_id, {"statuses": [{
            "id": wamid, "status": "delivered", "timestamp": ts,
            "recipient_id": sender,
            "conversation": {"id": "conv.%s" % uuid.uuid4().hex[:16],
                             "origin": {"type": "service"}},
            "pricing": {"billable": True, "pricing_model": "CBP", "category": "service"},
        }]})
    else:
        raise SystemExit("unknown payload kind %r" % kind)

    return _envelope(phone_number_id, {"contacts": contacts, "messages": [msg]})


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def read_body(args):
    if args.body_file == "-":
        return sys.stdin.buffer.read()
    with open(args.body_file, "rb") as fh:
        return fh.read()


def cmd_signature(args):
    raw = read_body(args)
    if args.verify:
        ok = verify(args.secret, raw, args.verify)
        print("valid" if ok else "INVALID")
        if not ok:
            print("expected %s" % sign(args.secret, raw))
            print("\nMost common cause: the body was parsed and re-serialised before "
                  "signing.\nSign the raw bytes exactly as received.")
        return 0 if ok else 1
    print(sign(args.secret, raw))
    return 0


def cmd_window(args):
    state = window_state(parse_iso(args.last_inbound),
                         parse_iso(args.now) if args.now else None)
    if args.json:
        print(json.dumps(state, indent=2))
        return 0
    hours, rem = divmod(state["remaining_seconds"], 3600)
    print("last inbound   %s" % state["last_inbound"])
    print("window closes  %s" % state["window_closes"])
    print("state          %s" % ("OPEN" if state["open"] else "CLOSED"))
    print("remaining      %dh %dm" % (hours, rem // 60))
    print("you may send   %s" % state["may_send"])
    print("\n%s" % state["note"])
    return 0 if state["open"] else 1


def cmd_payload(args):
    body = payload(args.kind, args.sender, args.phone_number_id, args.text, args.id)
    out = json.dumps(body, indent=2)
    print(out)
    if args.secret:
        sys.stderr.write("\nX-Hub-Signature-256: %s\n"
                         % sign(args.secret, json.dumps(body, indent=2).encode("utf-8")))
        sys.stderr.write("(signature computed over exactly the bytes printed above)\n")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="wa", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("signature", help="compute or verify X-Hub-Signature-256")
    s.add_argument("--secret", required=True)
    s.add_argument("--body-file", required=True, help="raw request body, or - for stdin")
    s.add_argument("--verify", help="header value to check, e.g. sha256=abc...")
    s.set_defaults(func=cmd_signature)

    w = sub.add_parser("window", help="24-hour service window state")
    w.add_argument("--last-inbound", required=True, help="ISO 8601, e.g. 2026-09-08T09:12:00Z")
    w.add_argument("--now", help="ISO 8601, defaults to now")
    w.add_argument("--json", action="store_true")
    w.set_defaults(func=cmd_window)

    d = sub.add_parser("payload", help="realistic webhook body for local testing")
    d.add_argument("kind", choices=["text", "audio", "image", "button", "status"])
    d.add_argument("--from", dest="sender", default="393331234567")
    d.add_argument("--phone-number-id", default="106540352242922")
    d.add_argument("--text", default="Buongiorno, vorrei prenotare per giovedi pomeriggio")
    d.add_argument("--id", help="reuse a wamid to test idempotency on a retry")
    d.add_argument("--secret", help="also print the matching signature on stderr")
    d.set_defaults(func=cmd_payload)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
