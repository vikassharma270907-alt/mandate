# Status and evidence

**Build:** Mandate v2.2 · sandbox prototype
**Dates:** deliverables due Nov 13, 2026 (build closes 10:29 AM PT). Finalists Nov 15; Demo Day Nov 19 in San Francisco, remote participation available. *(Dates per the Strategy & Research Guide v2.1.)*

---

## What is verified now

| Area | Evidence | Status |
|---|---|---|
| Policy decision changes with inputs | 9 documented scenarios, all matching | VERIFIED IN CODE |
| Exact scenario minima | Engine tests assert `12320`, `26000`, `28000`, `24320`, `320`, `14000`, `30000`, `25000`, `44000`, `15000`, `14999.99`, `13000`, `12500` | VERIFIED IN CODE |
| Strict money parsing | Rejects exponents, NaN/Inf, bool, whitespace, signs, commas, >2dp | VERIFIED IN CODE |
| Expected inflow/outflow treatment | Conservative case drops expected inflows; outflows always count; outflow-first ordering | VERIFIED IN CODE |
| Exact-floor safety | Balance 34,680 → annual minimum 15,000 → `PROPOSE_ANNUAL` | VERIFIED IN CODE |
| Live-plan checks | 32k HOLD, 21k HOLD, 20k FREEZE | VERIFIED IN CODE |
| Passport HMAC binding | Seven-field intent hash + record seal; tamper → INVALID | VERIFIED IN CODE |
| Passport precedence | INVALID → MISMATCH → EXPIRED → VALID | VERIFIED IN CODE |
| Card-control derivation | SINGLE/ALL_TIME and MULTIPLE/MONTHLY; USD/MCC allowlists; ceiling | VERIFIED IN CODE |
| Fake card enforcement | $19,680 declined; $2,000 approved; cumulative and single-use checks | VERIFIED IN CODE |
| Retry registry | One request ID per operation; fingerprint change rejected; terminal requires GET confirmation | VERIFIED IN CODE |
| Concurrent duplicate prevention | 16-thread same-operation and distinct-operation tests | VERIFIED IN CODE |
| Agent output validation | Control fields rejected; recommendation must be a decision | VERIFIED IN CODE |
| Injection handling | Four findings in the synthetic injection quote; disposition `IGNORED_AS_DATA` | VERIFIED IN CODE |
| End-to-end app flow | Run → approve → card → block → receipt → re-plan → fresh approval | VERIFIED IN CODE |
| Dashboard | Local stdlib server; all actions exercised via HTTP | VERIFIED IN CODE (local) |
| Full test suite | 120 tests passing on Python 3.14 | VERIFIED IN CODE |

Run:

```powershell
python -m mandate test
python -m mandate scenarios
python -m mandate demo
```

Last local run: **120 tests, OK, ~2 seconds**.

---

## What is not verified

| Area | Why | Status |
|---|---|---|
| Live Airwallex login | No sandbox credentials in this environment | UNCONFIRMED |
| Exact card-create payload | Must compare with current Kit 2 schema | UNCONFIRMED |
| Live card controls enforcement | Must create a card and see a decline in the sandbox | UNCONFIRMED |
| Live simulation deposit/authorization | Endpoint shapes are hypotheses | UNCONFIRMED |
| Live retry semantics | How Airwallex treats a retry after timeout is unknown | UNCONFIRMED |
| Live transactions response mapping | Parser is defensive but untested | UNCONFIRMED |
| Live LLM extraction path | Requires an OpenAI-compatible endpoint and key; offline demo uses a deterministic stand-in | UNCONFIRMED |
| Video recording | Script exists, recording not made | PLANNED |
| Hosted repository link | Public GitHub repository: https://github.com/vikassharma270907-alt/mandate | DONE |

The one-hour plan to close these is [`SANDBOX_RUNBOOK.md`](SANDBOX_RUNBOOK.md). Until it is executed and evidence captured, do not claim a live sandbox demo.

---

## Assumptions

- Monthly billing is modelled on a 4-week cadence, not calendar months.
- The horizon is inclusive weeks 0–8.
- The receivable is an expected inflow, not confirmed, until the receipt simulation lands it.
- The reserve floor is fixed at 15,000 USD for the demo.
- MCC 5734 and USD are the only allowed sandbox values.
- The fake sandbox's authorization does not hold available cash, so the post-receipt demo balance stays at 44,000 after an approved authorization. Real card authorizations would affect available funds.
- The SQLite registry is single-node.
- The dashboard is a local demo, not a hardened web application.
- The policy key is generated per process unless `MANDATE_PASSPORT_KEY` is set; restarting invalidates previously issued passports.

---

## Known limitations

1. **Live adapter shapes are unconfirmed.** `LiveAirwallexAdapter` is deliberately isolated and documented; it is not presented as working.
2. **No Visa TAP/VIC integration.** The Visa Award is not claimed.
3. **No payee bank account allowlisting.** Planned, not implemented.
4. **No production key management.** The demo uses an environment variable or a process-local random key.
5. **No distributed idempotency.** SQLite is single-node.
6. **The monthly cumulative card window vs the 4-week billing cadence.** A 4-week cycle can produce two charges inside one calendar month; the documented `MONTHLY` cap would block the second. This is a spec-level tension, not hidden. The demo avoids it by making one authorization per cycle.
7. **Authorization-only simulation.** Captures are supported by the fake adapter but the dashboard uses authorization-only to preserve the documented 44,000 balance.
8. **The demo agent is deterministic.** It is labelled as such. It exists so the walkthrough works offline; the live model path is separate.
9. **No real money movement.** Ever, in this prototype.

---

## Compliance map

| Requirement | Status |
|---|---|
| Change the decision when inputs change | VERIFIED IN CODE |
| Math and rules in deterministic code | VERIFIED IN CODE |
| Model only for unstructured inputs | VERIFIED IN CODE (prompt + validator) |
| Typed tools and bound human approvals | VERIFIED IN CODE |
| Isolate simulation calls | VERIFIED IN CODE (fake); live UNCONFIRMED |
| Spend limits in card controls | VERIFIED IN CODE (fake); live UNCONFIRMED |
| Working demo on the sandbox | UNCONFIRMED |
| Video under 5 minutes | PLANNED (4:45 script) |
| Repository with setup instructions | DONE (local) |
