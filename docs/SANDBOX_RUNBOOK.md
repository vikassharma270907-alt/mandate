# One-hour Airwallex sandbox verification plan

**Status: UNCONFIRMED.** Nothing in this runbook has been executed against a live Airwallex sandbox in this repository. The offline `FakeAirwallex` demo and the 120-test suite are verified. Treat every live request shape as a hypothesis to compare with the current Kit 2 schema.

The goal of the hour is evidence, not optimism: either you have a card-control block and a capture in `/issuing/transactions`, or you record exactly where the payload diverged.

---

## Before the clock starts

- Python 3.11+ and this repository on the machine.
- A sandbox account at `https://sandbox.airwallex.com` (the Strategy Guide uses the name *Sandbox Business* for the second business).
- Sandbox API key (not a production key).
- Access to the Airwallex API docs / Kit 2 schema for issuing.
- A scratch note for request IDs, HTTP statuses and response bodies.
- **Do not** point any of this at production.

PowerShell environment:

```powershell
$env:AIRWALLEX_API_KEY = "<sandbox-api-key>"
$env:AIRWALLEX_BASE_URL = "https://api-demo.airwallex.com"
$env:AIRWALLEX_API_VERSION = "2022-11-11"
$env:AIRWALLEX_CARD_PROGRAM_ID = "<if the account requires one>"
```

Keep the key out of shell history in a real run (use a secret manager or a temporary environment block).

---

## Minutes 0–15: schema comparison

1. Sign in to the sandbox and create/copy a sandbox API key.
2. Open the current issuing card-create schema in the Airwallex docs (Docs MCP `/docs` or the developer portal).
3. Compare it with the payload produced by `card_controls_from_passport()`:

```json
{
  "allowed_transaction_count": "MULTIPLE",
  "allowed_currencies": ["USD"],
  "allowed_merchant_categories": ["5734"],
  "transaction_limits": {
    "currency": "USD",
    "limits": [
      {"amount": 2000.0, "interval": "PER_TRANSACTION"},
      {"amount": 2000.0, "interval": "MONTHLY"}
    ]
  }
}
```

Record differences before calling anything. The live adapter in `mandate/sandbox.py` currently sends these fields directly plus `request_id` (and `card_program_id` if configured). That shape is **UNCONFIRMED**.

If the schema requires a wrapper (for example `card_controls` or a different limit interval spelling), stop and fix the adapter before proceeding. Do not paper over the difference with a fake result.

---

## Minutes 15–30: authenticate, read cash, deposit

Run a small read-only probe first:

```powershell
python -c "import sys; sys.path.insert(0, '.'); from mandate.sandbox import LiveAirwallexAdapter; a = LiveAirwallexAdapter(); print('token', a.authenticate()[:12] + '...'); print('balance', a.available_balance())"
```

The adapter calls:

- `POST /api/v1/authentication/login` with `x-api-key` and `x-api-version`
- `GET /api/v1/balances/current?currency=USD`

Confirm that:

- login returns a bearer token;
- the balance response is parsed from `available_amount`, **not** `total_amount`;
- USD is the only currency used.

Seed the demo deposit:

```powershell
python -c "import sys; sys.path.insert(0, '.'); from mandate.sandbox import LiveAirwallexAdapter; a = LiveAirwallexAdapter(); print(a.deposit('32000.00'))"
```

This calls `POST /api/v1/simulation/deposit/create`. Verify the new `available_amount` with a second balance read. Do not proceed until the balance is visible.

> The expected receivable, reserve floor and all policy numbers are synthetic configuration in the application. The cash balance itself is the live sandbox number.

---

## Minutes 30–45: card, block, capture

The application can drive the whole flow against the live adapter:

```powershell
@'
import sys
sys.path.insert(0, ".")
from mandate.application import MandateApplication
from mandate.sandbox import LiveAirwallexAdapter

app = MandateApplication(adapter=LiveAirwallexAdapter())
state = app.run_policy()
print("decision:", state["proposal"]["decision"])
print("terms:", state["proposal"]["submitted_intent"])
# Only after reviewing the exact terms:
state = app.approve(state["proposal"]["approval_token"])
print("passport:", state["passport"]["validation_status"])
print("card:", state["card"]["id"])

print("annual attempt:", app.simulate_authorization("19680.00"))
print("monthly attempt:", app.simulate_authorization("2000.00"))
'@ | python -
```

Expected, if the schema is right:

1. Policy selects `PROPOSE_MONTHLY` on a fresh $32,000 balance with the expected receivable still pending.
2. Passport validates `VALID`.
3. Card is created with a $2,000 per-transaction and monthly cap.
4. The $19,680 authorization is declined or otherwise blocked by card controls.
5. The $2,000 authorization is approved.
6. `GET /api/v1/issuing/transactions` shows both attempts.

The failure mode is informative. Record:

| Check | Evidence | Result |
|---|---|---|
| Login token | HTTP status + token prefix | |
| Balance source | raw `available_amount` | |
| Deposit visible | balance before/after | |
| Card created | card id + response | |
| $19,680 blocked | status + decline code/reason | |
| $2,000 approved | status + transaction id | |
| Transactions list | both attempts present | |
| Retry request ID | same ID on replay | |

If the card-create payload needs a different shape, update `LiveAirwallexAdapter.create_card()` and the docs. Do not change the deterministic controls payload without updating tests.

---

## Minutes 45–60: idempotency and evidence

Retry probe (offline, but demonstrates the registry contract):

```powershell
python -c "import sys; sys.path.insert(0, '.'); from mandate.retry_registry import RetryRegistry, fingerprint_payload; import tempfile, os; p=os.path.join(tempfile.gettempdir(),'mandate-live-retry.sqlite'); r=RetryRegistry(p); fp=fingerprint_payload({'amount':'2000.00'}); a=r.begin_operation('live-op',fp); b=r.begin_operation('live-op',fp); print(a.request_id, b.request_id, b.replay)"
```

For a live retry, use the registry around the exact card-create request. The same operation must reuse the same request ID. `FAILED_TERMINAL` is only allowed after a GET confirms the operation is closed.

Capture evidence:

- screenshots of the card in the sandbox UI;
- the create-card response (redact the key);
- the two authorization responses;
- the transactions list;
- the exact API version and timestamp.

Then update [`STATUS.md`](STATUS.md): mark each row VERIFIED or still UNCONFIRMED. Do not mark the live demo complete based on the fake adapter.

---

## Known schema risks

These are the things most likely to diverge. Check them against the current Kit 2 docs:

1. Whether `transaction_limits` belongs at the top level or inside a `card_controls` object.
2. Whether the limit amount must be an integer in minor units instead of a major-unit number.
3. Whether `allowed_transaction_count` uses `SINGLE`/`MULTIPLE` or different enum values.
4. Whether `PER_TRANSACTION` / `MONTHLY` / `ALL_TIME` are the exact interval strings.
5. Whether `request_id` is accepted on card creation and what its uniqueness rules are.
6. Whether a card program ID or card product ID is mandatory.
7. Whether the simulation issuing endpoint uses `card_id`, `pan` or another identifier.
8. How Airwallex treats a retry after a timeout: replay safe, duplicate, or 409.

If any of these differ, the deterministic policy and passport layers stay the same. Only the adapter mapping changes.

---

## Rollback / cleanup

- The fake adapter is in-memory and resets on restart.
- The live sandbox may leave a card and transactions behind. Use the sandbox UI to close the card if needed.
- Delete any local SQLite retry file after the run if it contains sandbox identifiers.
- Rotate the sandbox API key if it was pasted into a shell transcript or screenshot.

## What not to claim

Do not claim a live sandbox demo until:

- the card was actually created;
- the block is visible in the sandbox, not just in the fake adapter;
- the approved charge is visible in `/issuing/transactions`;
- the evidence is captured.

Until then, the correct status is **UNCONFIRMED**.
