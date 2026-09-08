"""
Standalone sanity checks for the signed auth-cookie token helpers in auth.py.
Run: expense_env/bin/python tests_auth_token.py
"""
import sys
import time

from auth import make_auth_token, verify_auth_token, get_cookie_secret, REMEMBER_DAYS
from config import ALLOWED_USERS

SECRET = "unit-test-secret"
NOW = 1_800_000_000
USER = ALLOWED_USERS[0]
failures = 0


def check(name, cond):
    global failures
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures += 1


# 1. round-trip
tok = make_auth_token(USER, days=REMEMBER_DAYS, secret=SECRET, now=NOW)
check("token has payload.signature shape", tok.count(".") == 1 and len(tok.rpartition(".")[2]) == 64)
res = verify_auth_token(tok, secret=SECRET, now=NOW)
check("round-trip verifies", res is not None and res["user"] == USER)
check("exp == now + 30 days", res is not None and res["exp"] == NOW + REMEMBER_DAYS * 86400)

# 2. tampered signature
payload_b64, _, sig = tok.rpartition(".")
bad_sig = ("0" if sig[0] != "0" else "1") + sig[1:]
check("tampered signature fails", verify_auth_token(payload_b64 + "." + bad_sig, secret=SECRET, now=NOW) is None)

# 2b. tampered payload (signature unchanged)
other_tok = make_auth_token(USER, days=365, secret=SECRET, now=NOW)
other_payload = other_tok.rpartition(".")[0]
check("tampered payload fails", verify_auth_token(other_payload + "." + sig, secret=SECRET, now=NOW) is None)

# 2c. wrong secret
check("wrong secret fails", verify_auth_token(tok, secret="another-secret", now=NOW) is None)

# 3. expired
check("expired token fails", verify_auth_token(tok, secret=SECRET, now=NOW + REMEMBER_DAYS * 86400 + 1) is None)
check("token at exact exp fails", verify_auth_token(tok, secret=SECRET, now=NOW + REMEMBER_DAYS * 86400) is None)

# 4. unknown user
bad_user_tok = make_auth_token("不存在的人", days=REMEMBER_DAYS, secret=SECRET, now=NOW)
check("unknown user fails", verify_auth_token(bad_user_tok, secret=SECRET, now=NOW) is None)

# 5. garbage inputs
for garbage in (None, "", "abc", "abc.", ".abc", "not-base64!.deadbeef", 12345):
    check(f"garbage input rejected: {garbage!r}", verify_auth_token(garbage, secret=SECRET, now=NOW) is None)

# 6. default secret path (no explicit secret) works and is deterministic
tok_default = make_auth_token(USER)
check("default secret round-trip", verify_auth_token(tok_default) is not None)
check("default secret is deterministic", get_cookie_secret() == get_cookie_secret())

print(f"\n{'ALL PASSED' if failures == 0 else f'{failures} FAILED'}")
sys.exit(1 if failures else 0)
