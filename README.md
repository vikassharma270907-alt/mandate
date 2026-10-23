# Mandate

**Intent-bound purchase agent for the Airwallex Agentic Banking Hackathon — Track 2.**

A founder needs to choose how to pay a SaaS bill: monthly or annual. Annual is cheaper, but writing the full prepayment can break the cash reserve before a customer receipt lands. A language model is useful for reading the vendor quote, but it must never decide money, set a card limit, or hold credentials.

Mandate separates those jobs:

- **The deterministic engine decides** whether the purchase is `PROPOSE_ANNUAL`, `PROPOSE_MONTHLY` or `DEFER`.
- **The model only reads** untrusted documents and explains the result.
- **The human approves exact terms**, bound into a sealed Decision Passport.
- **The card enforces the limits**, not the prompt.

> Sandbox prototype using synthetic demo data only. Not production banking software.

---

## The 20-second pitch

```text
Balance $32,000 · floor $15,000 · expected $12,000 receivable at week 4
Annual $19,680  -> minimum $12,320 at week 0  -> BREACH by $2,680
Monthly 3 × $2,000 -> minimum $26,000 at week 8 -> SAFE
Engine: PROPOSE_MONTHLY

Receivable lands -> balance $44,000
Annual $19,680 -> minimum $24,320 at week 0 -> SAFE
Engine: PROPOSE_ANNUAL (saves $4,320/year)

The monthly card still declines a $19,680 charge.
A fresh human approval and a fresh passport are required.
```

The same quote produces different answers as cash and timing change. That is the point.

---

## Quick start

Requires Python 3.11+ (tested on Python 3.14). **No third-party packages.**

```powershell
# From the repository root
python -m mandate demo          # full terminal walkthrough
python -m mandate scenarios     # the nine documented engine scenarios
python -m mandate serve         # local dashboard at http://127.0.0.1:8765
python -m mandate test          # full test suite
```

If your shell cannot find the package, run from the repository root or install it:

```powershell
python -m pip install -e .
mandate serve
```

### Dashboard walkthrough

1. Open `http://127.0.0.1:8765`.
2. Click **Run the policy engine**. The engine selects `PROPOSE_MONTHLY`; annual is `$2,680` below the floor.
3. Review the exact terms and click **Approve & issue card**. A passport and a card with a `$2,000` per-transaction/monthly cap are created.
4. Click **Try annual $19,680** → declined by the card. Click **Try monthly $2,000** → approved. These are authorization-only simulations; no funds move.
5. Click **Land receipt**. The balance becomes `$44,000` and the pending proposal is marked stale.
6. Click **Re-run engine** → `PROPOSE_ANNUAL`. The old monthly card still declines the annual charge; approve the new terms to issue a fresh annual card.
7. Use the **Security lab** to run the prompt-injection, passport-tamper and retry-ID probes.

The dashboard is served by the Python standard library. It binds to localhost by default.

---

## Architecture and trust boundaries

```text
                    TRUSTED                                   UNTRUSTED
┌─────────────────────────────────────────┐        ┌──────────────────────────┐
│ Application                             │        │ Vendor quote / email     │
│  · builds trusted context               │        │  · text, OCR, web page   │
│  · calls policy engine                  │        │  · instructions are data │
│  · validates model JSON                 │        └────────────┬─────────────┘
│  · binds human approval                 │                     │
│  · derives card controls                │                     ▼
│  · calls the sandbox adapter             │        ┌──────────────────────────┐
└───────┬──────────────────┬──────────────┘        │ Mandate Agent Prompt     │
        │                  │                       │  · extract               │
        ▼                  ▼                       │  · compare               │
┌───────────────┐  ┌──────────────────────┐        │  · explain               │
│ Policy Engine │  │ Decision Passport    │        │  · JSON only             │
│  · forecast   │  │  · 7-field HMAC      │        └────────────┬─────────────┘
│  · floor      │  │  · record seal       │                     │
│  · decision   │  │  · status precedence │                     ▼
└───────┬───────┘  └──────────┬───────────┘        ┌──────────────────────────┐
        │                     │                    │ Model output             │
        ▼                     ▼                    │  · untrusted until       │
┌─────────────────────────────────────────┐        │    validated             │
│ Card controls                           │        │  · never sets limits     │
│  · SINGLE/ALL_TIME or MULTIPLE/MONTHLY  │        └──────────────────────────┘
│  · approved amount caps                 │
│  · USD and MCC 5734 allowlists          │
└───────────────────┬─────────────────────┘
                    ▼
┌─────────────────────────────────────────┐
│ Airwallex sandbox adapter               │
│  · the only code that calls /api/v1     │
│  · fake adapter for offline demo/tests  │
└─────────────────────────────────────────┘
```

### Data flow for one request

1. The application reads **trusted cash** from the adapter (`available_amount`, not `total_amount`) and builds a `CashContext`.
2. The deterministic engine computes the annual and monthly forecasts and returns a flat `policy_result`.
3. The application sends one envelope to the agent: `request_id`, `trusted_context`, `policy_result`, `passport`, `passport_status`, `untrusted_documents`, `trigger`.
4. The agent extracts terms with source and confidence, reports discrepancies, flags injection attempts, and echoes the policy decision.
5. The application validates the JSON. Control fields such as `card_controls` cause a hard rejection; the model cannot set limits.
6. A human approves the exact seven fields. The application issues a sealed passport and derives card controls.
7. The card adapter enforces the controls. The model has no path to the card payload.

---

## Deterministic policy engine

`mandate/mandate_policy_engine.py` is side-effect free: no I/O, no clock, no network.

### Forecast rules

- Inclusive horizon: weeks `0..8`.
- Monthly billing uses a `4`-week cadence: weeks `0, 4, 8` by default, configurable with `monthly_first_week`.
- Money is parsed as `Decimal` major units. Exponents, `NaN`, infinities, booleans, whitespace, signs, commas and more than two decimals are rejected.
- Flow kinds: confirmed inflow, expected inflow, committed outflow, expected outflow. Amounts are positive; the kind carries direction.
- The conservative case drops **expected inflows only**. Expected outflows always count.
- Within a week, outflows are applied and the minimum is checked **before** inflows are added.
- A balance exactly at the reserve floor is safe (`>=`).
- Purchase flows outside the horizon are rejected, never silently ignored.
- `available_balance` must be the wallet's `available_amount`.

### Decision table

1. Annual is cash-safe **and** annual saving is greater than zero → `PROPOSE_ANNUAL`
2. Otherwise, monthly is cash-safe → `PROPOSE_MONTHLY`
3. Otherwise → `DEFER`

Annual saving is `12 × monthly_price − annual_price`. Cash-safe means the confirmed-cash minimum is at or above the floor.

### Lifecycle

- `policy_output()` returns the flat prompt-facing result: decision, reason, policy version, floor, minima and weeks, annual saving, payment schedules, assumptions and the live-plan decision.
- `evaluate_live_plan(context, terms, remaining_payments, plan=...)` re-checks an approved plan against current confirmed cash. It returns only `HOLD` or `RECOMMEND_FREEZE_AND_ESCALATE`; it never freezes a card itself.

### Nine documented scenarios

All rows are verified by tests. Every row uses a fresh context.

| # | Scenario | Annual min | Monthly min | Result |
|---|---|---|---|---|
| 1 | Initial: balance 32,000, expected 12,000 at week 4 | 12,320 (w0) | 26,000 (w8) | `PROPOSE_MONTHLY` |
| 2 | Receipt landed: balance 44,000, no pending inflow | 24,320 (w0) | 38,000 (w8) | `PROPOSE_ANNUAL`; saves 4,320 |
| 3 | Receipt confirmed but scheduled week 4 | 12,320 (w0) | 28,000 (w4) | `PROPOSE_MONTHLY` |
| 4 | Balance 20,000 | 320 (w0) | 14,000 (w8) | `DEFER` |
| 5 | Balance 32,000, confirmed inflow week 3, annual paid week 4 | 24,320 (w4) | 30,000 (w0) | `PROPOSE_ANNUAL` |
| 6 | Monthly 2,000, annual 25,000, balance 50,000 | 25,000 (w0) | 44,000 (w8) | `PROPOSE_MONTHLY`; annual costs 1,000 more |
| 7 | Balance 34,680: annual lands exactly on floor | 15,000 (w0) | 28,680 (w8) | `PROPOSE_ANNUAL` |
| 8 | Balance 34,679.99: one cent under | 14,999.99 (w0) | 28,679.99 (w8) | `PROPOSE_MONTHLY` |
| 9 | Balance 17,000, expected outflow 3,000 at week 1, prices 500/1,000 | 13,000 (w1) | 12,500 (w8) | `DEFER` |

A complete engine output for scenario 1 is in [`examples/scenario_01_policy_output.json`](examples/scenario_01_policy_output.json).

Live-plan re-check (monthly, three payments left):

| Current balance | Confirmed low | Result |
|---|---|---|
| 32,000 | 26,000 (w8) | `HOLD` |
| 21,000 | 15,000 (w8) | `HOLD` (exactly at floor) |
| 20,000 | 14,000 (w8) | `RECOMMEND_FREEZE_AND_ESCALATE` |

---

## Decision Passport

`mandate/passport.py`

A passport binds what the human actually approved.

**Seven approved fields:** `vendor`, `amount`, `currency`, `billing_cadence`, `merchant_category`, `evidence_reference`, `policy_version`.

**Other fields:** `approval_id`, `intent_hash`, `approval_expiry`, `approval_status`, `record_seal`.

- `intent_hash` is HMAC-SHA256 with a server-side key of at least 32 bytes over the seven fields.
- `record_seal` is a second keyed MAC over the stored record, so approval ID, status, expiry and the hash cannot be altered in storage.
- Normalisation: NFKC and whitespace collapse; currency and cadence ignore case; cadence must be exactly `MONTHLY` or `ANNUAL`; MCC must be four ASCII digits.
- Status precedence: `INVALID`, then `MISMATCH`, then `EXPIRED`, then `VALID`.
- The human-approval endpoint also requires an approval token bound to the proposal ID and exact intent. A stale proposal cannot be approved.

The dashboard shows the intent hash, record seal and current-intent match. The tamper probe changes the amount and demonstrates `INVALID`.

---

## Card controls

`mandate/card_controls.py`

| Approved cadence | Transaction count | Cumulative interval | Caps |
|---|---|---|---|
| `ANNUAL` | `SINGLE` | `ALL_TIME` | Approved amount |
| `MONTHLY` | `MULTIPLE` | `MONTHLY` | Approved amount |

`card_controls_from_passport()` requires a `VALID` passport and enforces:

- currency and MCC in trusted allowlists (`USD`, `5734` in the sandbox);
- an optional `max_amount` ceiling that catches a cents-for-dollars (100×) error;
- non-empty arrays (empty arrays would leave cards unrestricted);
- no vendor name or extracted text in the payload.

Payload shape:

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

The fake sandbox enforces this payload for real (in memory): the $19,680 annual charge is declined on the monthly card, $2,000 passes, the cumulative cap blocks a second $2,000 in the same month, and the annual card is single-use.

---

## Retry registry and idempotency

`mandate/retry_registry.py`

- One logical operation maps to one random request ID.
- Every claim/update runs in a SQLite `BEGIN IMMEDIATE` write transaction.
- `IN_FLIGHT`, `FAILED_RETRYABLE` and `SUCCEEDED` replay the same request ID.
- `FAILED_TERMINAL` closes the operation; retrying requires a new operation after a fresh policy check.
- A changed fingerprint for an existing operation is rejected.
- `FAILED_TERMINAL` can only be recorded with `terminal_confirmed=True`, representing a GET that confirmed terminal state.
- A 16-thread test proves one operation gets one request ID under a concurrent race.

The SQLite registry is built for single-node deployments.

---

## Agent boundary

`mandate/agent.py` and `prompts/mandate_system_prompt.txt`

The prompt restricts the model to extraction, comparison, explanation and a recommendation label that **must equal** the engine decision. It must quote engine numbers exactly and never recalculate them. Untrusted documents are data; embedded instructions are flagged as `IGNORED_AS_DATA`.

The validator rejects the entire response if it contains control fields such as `card_controls`, `controls`, `transaction_limits`, `passport` or `approval_status`. The application also overrides `policy_decision` with the engine decision and adds a discrepancy if the model disagrees.

**Offline demo:** `DemoAgent` is a deterministic stand-in that parses the synthetic quote fixture. It is labelled `demo-deterministic` in the UI so it is never confused with a live model.

**Live LLM:** use any OpenAI-compatible endpoint (for example a local Ollama server):

```powershell
$env:MANDATE_LLM_BASE_URL = "http://127.0.0.1:11434/v1"
$env:MANDATE_LLM_MODEL = "qwen2.5-coder:7b"
$env:MANDATE_LLM_API_KEY = ""   # optional for local Ollama
python -m mandate serve --agent llm
```

The prompt file is the contract. The live model path is exercised only when configured; the offline demo does not require network access.

---

## Live Airwallex sandbox

`mandate/sandbox.py` contains the only code that calls `/api/v1`. The live adapter is **UNCONFIRMED** until its payloads are compared with the current Kit 2 schema and exercised against a real sandbox.

```powershell
$env:AIRWALLEX_API_KEY = "..."
$env:AIRWALLEX_BASE_URL = "https://api-demo.airwallex.com"
$env:AIRWALLEX_API_VERSION = "2022-11-11"
$env:AIRWALLEX_CARD_PROGRAM_ID = "..."   # if required by the account
```

Endpoints used by the adapter:

- `POST /api/v1/authentication/login`
- `GET /api/v1/balances/current`
- `POST /api/v1/simulation/deposit/create`
- `POST /api/v1/issuing/cards/create`
- `POST /api/v1/simulation/issuing/create`
- `GET /api/v1/issuing/transactions`

The exact card-create payload shape and every live endpoint behaviour remain unconfirmed. See [`docs/SANDBOX_RUNBOOK.md`](docs/SANDBOX_RUNBOOK.md) for the one-hour verification plan. Do not represent a live run as complete until it has actually been executed.

---

## Tests

```powershell
python -m mandate test
# or
python -m unittest discover -s tests -v
```

**120 tests, all passing.** The deterministic engine has its own **47-test suite** (`tests/test_mandate_policy_engine.py`), covering:

- strict money parsing and validation;
- all nine scenarios and exact minima;
- outflow-first ordering, expected inflow/outflow treatment and exact-floor safety;
- live-plan hold/freeze cases;
- flat policy output fields and assumptions.

Additional suites cover passport seals and precedence, card controls, fake-card enforcement, the retry race, the agent boundary and the end-to-end application flow.

---

## Requirement compliance map

| Requirement | How Mandate meets it | Status |
|---|---|---|
| Change the decision when inputs change | Same quote yields monthly, annual or defer as balance, receipt timing or live cash changes | **VERIFIED IN CODE** |
| Math and rules in deterministic code | Forecast, floor, validation, hashing, limits and state are in Python; the prompt quotes engine numbers | **VERIFIED IN CODE** |
| Model only for unstructured input | Prompt + validator restrict the model to extraction/comparison/explanation | **VERIFIED IN CODE (prompt + validator)** |
| Typed tools and bound human approvals | HMAC over seven fields plus a sealed passport record and approval token | **VERIFIED IN CODE** |
| Isolate simulation calls | `sandbox.py` is the only `/api/v1` caller; fake adapter for demo/tests | **VERIFIED IN CODE (fake); live UNCONFIRMED** |
| Spend limits live in card controls | Controls derived only from a valid passport and enforced by the fake card | **VERIFIED IN CODE (fake); live UNCONFIRMED** |
| Working demo on the sandbox | Offline fake demo works today; live sandbox run pending credentials and schema check | **UNCONFIRMED** |
| Video walkthrough under 5 minutes | Script provided at [`docs/VIDEO_SCRIPT.md`](docs/VIDEO_SCRIPT.md), target 4:45 | **PLANNED** |
| Repository link with setup instructions | Local repository and README with setup instructions; hosted remote not configured | **DONE (local); REMOTE PENDING** |

---

## Repository layout

```text
mandate/
  application.py             trusted orchestration, approval binding, snapshots
  mandate_policy_engine.py   deterministic forecast and decision table
  money.py                   strict Decimal parsing/formatting
  passport.py                HMAC passport issue + validation
  card_controls.py           passport -> card control payload
  retry_registry.py          SQLite idempotency registry
  sandbox.py                 fake sandbox + live Airwallex adapter
  agent.py                   prompt boundary, demo agent, OpenAI-compatible agent
  demo.py                    terminal walkthrough and scenario table
  web.py                     stdlib HTTP server
  static/index.html          dashboard
prompts/
  mandate_system_prompt.txt  agent contract
fixtures/
  quote_cloudmetrics.txt     synthetic vendor quote
  injection_quote.txt        synthetic prompt-injection document
examples/
  scenario_01_policy_output.json  sample deterministic engine output
tests/                       120 tests
docs/
  ARCHITECTURE.md            trust boundaries and sequence
  SANDBOX_RUNBOOK.md         one-hour live verification plan
  VIDEO_SCRIPT.md            4:45 walkthrough script
  STATUS.md                  status, assumptions and limitations
```

---

## Status labels

- **VERIFIED IN CODE** — demonstrated by the test suite or by running the engine on the documented scenarios.
- **PER STRATEGY GUIDE** — hackathon dates, rules, sandbox behaviour and endpoint facts as stated in the Strategy & Research Guide (v2.1).
- **UNCONFIRMED** — not yet run against a live Airwallex sandbox. Includes the exact card-create payload shape, live endpoint behaviour, and retry-after-failure semantics.
- **ASSUMED** — a modelling or configuration choice, listed below.

## Known limitations and assumptions

- All Airwallex behaviour remains **UNCONFIRMED** until run against live sandbox APIs.
- Monthly billing is modelled on a 4-week cadence as an approximation of calendar months.
- The Visa Award is not claimed; this build does not integrate Visa TAP or VIC tooling.
- The SQLite retry registry is built for single-node deployments.
- Payee bank account allowlisting is planned but not implemented.
- The dashboard and fake sandbox are demo tools; they are not a production banking UI.
- The monthly card's `MONTHLY` cumulative interval can conflict with a 4-week billing cadence in some calendar months. This is a deliberate reflection of the documented card-control spec; a production design should align the cadence and the cumulative window.
- The fake sandbox's authorization simulation does not place a hold on available cash, so the demo's `$44,000` post-receipt balance matches the documented scenario. Real card authorizations would affect available funds.
- All names, amounts, quotes and transactions are synthetic demo fixtures: balance 32,000; floor 15,000; monthly 2,000; annual 19,680; expected receivable 12,000; horizon 8 weeks; MCC 5734; USD only.

## Safety

This is a hackathon prototype. It does not move real money, issue real cards, store real bank credentials, or provide financial advice. The live adapter requires explicit sandbox credentials and remains unverified by design. Do not point it at production.
