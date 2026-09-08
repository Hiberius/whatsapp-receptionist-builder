#!/usr/bin/env python3
"""Zero-dependency test suite. Run: python3 tests/test_wa.py"""
import datetime as dt
import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import wa  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILED.append(name)


print("signature")
body = b'{"object":"whatsapp_business_account","entry":[]}'
sig = wa.sign("s3cret", body)
check("prefixed with sha256=", sig.startswith("sha256="))
check("matches a hand computed hmac",
      sig == "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest())
check("verifies its own signature", wa.verify("s3cret", body, sig))
check("rejects a wrong secret", not wa.verify("other", body, sig))
check("rejects a tampered body", not wa.verify("s3cret", body + b" ", sig))
check("rejects an empty header", not wa.verify("s3cret", body, ""))
check("rejects a missing header", not wa.verify("s3cret", body, None))
check("tolerates surrounding whitespace", wa.verify("s3cret", body, " %s " % sig))
reserialised = json.dumps(json.loads(body.decode())).encode()
check("re-serialising the body breaks the digest, as it does in production",
      not wa.verify("s3cret", reserialised, sig) or reserialised == body)

print("service window")
base = dt.datetime(2026, 9, 8, 9, 12, tzinfo=dt.timezone.utc)
s = wa.window_state(base, base + dt.timedelta(hours=5))
check("open inside 24 hours", s["open"])
check("free-form allowed inside", s["may_send"] == "free-form")
check("remaining is 19 hours", s["remaining_seconds"] == 19 * 3600)
s = wa.window_state(base, base + dt.timedelta(hours=24, seconds=1))
check("closed one second after 24 hours", not s["open"])
check("template only outside", "template" in s["may_send"])
check("remaining never goes negative", s["remaining_seconds"] == 0)
s = wa.window_state(base, base + dt.timedelta(hours=23, minutes=59, seconds=59))
check("still open one second before the boundary", s["open"])

print("timestamp parsing")
check("Z suffix is accepted",
      wa.parse_iso("2026-09-08T09:12:00Z").tzinfo is not None)
check("offset is preserved",
      wa.parse_iso("2026-09-08T11:12:00+02:00").utcoffset().total_seconds() == 7200)
check("naive input is treated as utc",
      wa.parse_iso("2026-09-08T09:12:00").utcoffset().total_seconds() == 0)

print("payloads")
p = wa.payload("text", "393331234567", "1065", "ciao", None)
value = p["entry"][0]["changes"][0]["value"]
check("text payload carries a message", len(value["messages"]) == 1)
check("text payload carries the body", value["messages"][0]["text"]["body"] == "ciao")
check("sender is preserved", value["messages"][0]["from"] == "393331234567")
check("phone number id is preserved", value["metadata"]["phone_number_id"] == "1065")

p = wa.payload("audio", "393331234567", "1065", "", None)
msg = p["entry"][0]["changes"][0]["value"]["messages"][0]
check("audio payload is a voice note", msg["audio"]["voice"] is True)
check("audio arrives as an id, not a url", "id" in msg["audio"] and "url" not in msg["audio"])
check("audio mime type is opus ogg", "opus" in msg["audio"]["mime_type"])

p = wa.payload("status", "393331234567", "1065", "", "wamid.X")
value = p["entry"][0]["changes"][0]["value"]
check("status payload has no messages key", "messages" not in value)
check("status payload has statuses", value["statuses"][0]["status"] == "delivered")
check("status payload has no from field", "from" not in value["statuses"][0])

a = wa.payload("text", "39333", "1065", "x", "wamid.SAME")
b = wa.payload("text", "39333", "1065", "x", "wamid.SAME")
check("a reused wamid produces the same id, for idempotency tests",
      a["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
      == b["entry"][0]["changes"][0]["value"]["messages"][0]["id"])
a = wa.payload("text", "39333", "1065", "x", None)
b = wa.payload("text", "39333", "1065", "x", None)
check("generated wamids are unique",
      a["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
      != b["entry"][0]["changes"][0]["value"]["messages"][0]["id"])

print("")
if FAILED:
    print("%d test(s) failed: %s" % (len(FAILED), ", ".join(FAILED)))
    sys.exit(1)
print("all tests passed")
