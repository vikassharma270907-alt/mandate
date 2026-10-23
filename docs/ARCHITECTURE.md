# Architecture

## Design rule

> Math and rules live in code. The model reads unstructured input only. Every human approval is bound to the exact terms and evidence shown. Simulation calls sit behind one interface.

Mandate is a sandbox prototype. It does not move money, issue real cards, or claim production readiness.

## Components

| # | Component | Trust | File |
|---|---|---|---|
| 1 | Application | Trusted | `mandate/application.py` |
| 2 | Policy engine | Trusted | `mandate/mandate_policy_engine.py` |
| 3 | Mandate agent prompt | Model-facing | `prompts/mandate_system_prompt.txt` |
| 4 | Airwallex sandbox adapter | Trusted boundary | `mandate/sandbox.py` |
| 5 | Retry registry | Trusted state | `mandate/retry_registry.py` |
| 6 | Decision Passport | Trusted, sealed | `mandate/passport.py` |
| 7 | Card controls | Trusted derivation | `mandate/card_controls.py` |

The **application** is the only orchestrator. It assembles the model envelope, calls the engine, validates model JSON, shows terms to the approver, issues the passport, derives card controls and talks to the adapter.

The **policy engine** is side-effect free. It has no clock, no file access and no network. Given the same context and terms, it always produces the same decision.

The **agent** receives untrusted documents plus trusted policy numbers. It returns JSON only. Its output is untrusted until the application validates it.

The **adapter** is the only code allowed to call `/api/v1`. `FakeAirwallex` implements the same control checks in memory. `LiveAirwallexAdapter` is UNCONFIRMED until exercised against a real sandbox.

## Trust table

| Data | Trust | Treatment |
|---|---|---|
| `trusted_context` (balance, floor, horizon, flows, purchase request) | Trusted | Built by the application from the adapter and configuration |
| `policy_result` | Trusted | Produced by the deterministic engine |
| `passport`, `passport_status` | Trusted | Sealed by the application; validated before use |
| `untrusted_documents` (quotes, emails, PDFs, OCR, web pages) | Untrusted | Data only; instructions are flagged and ignored |
| Model output | Untrusted until validated | JSON schema validation; control fields are a hard rejection |
| Card controls | Trusted derivation | Only from a VALID passport; allowlists and ceilings enforced |

## Sequence: one purchase request

```text
Human/UI          Application              Engine          Agent             Adapter
   │                  │                      │               │                  │
   │  run policy      │                      │               │                  │
   ├─────────────────>│                      │               │                  │
   │                  │ available_amount     │               │                  │
   │                  ├─────────────────────────────────────────────────────────>│
   │                  │<─────────────────────────────────────────────────────────┤
   │                  │ evaluate(context, terms)             │                  │
   │                  ├─────────────────────>│               │                  │
   │                  │ policy_result        │               │                  │
   │                  │<─────────────────────┤               │                  │
   │                  │ envelope(docs, policy)               │                  │
   │                  ├─────────────────────────────────────>│                  │
   │                  │ JSON: extraction, explanation        │                  │
   │                  │<─────────────────────────────────────┤                  │
   │                  │ validate; reject control fields      │                  │
   │                  │ build submitted_intent from terms    │                  │
   │  exact terms     │                      │               │                  │
   │<─────────────────┤                      │               │                  │
   │  approve(token)  │                      │               │                  │
   ├─────────────────>│                      │               │                  │
   │                  │ issue sealed passport│               │                  │
   │                  │ validate (VALID)     │               │                  │
   │                  │ derive card controls │               │                  │
   │                  │ create card (idempotent)             │                  │
   │                  ├─────────────────────────────────────────────────────────>│
   │                  │ card                 │               │                  │
   │                  │<─────────────────────────────────────────────────────────┤
   │  card controls   │                      │               │                  │
   │<─────────────────┤                      │               │                  │
   │  authorize 19,680│                      │               │                  │
   ├─────────────────>│──────────────────────────────────────────────────────────>│
   │  DECLINED        │                      │               │                  │
   │<─────────────────┤<──────────────────────────────────────────────────────────┤
```

## State machine

```text
NO_PROPOSAL
    │ run_policy()
    ▼
PENDING_APPROVAL ──approve(token)──> APPROVED
    │                                   │
    │ receipt lands                     │ receipt lands
    ▼                                   ▼
  STALE                           APPROVED (old card remains)
    │                                   │
    │ run_policy()                      │ run_policy() -> new proposal
    ▼                                   ▼
PENDING_APPROVAL                    PENDING_APPROVAL

DEFERRED (no approval path)
```

A new policy run does not silently revoke an existing card. It creates a new proposal. The old passport can still validate on its own terms, but `passport_matches_current_intent` becomes `MISMATCH`; a fresh human approval is required for the new terms.

## Invariants

1. The model never produces the decision used to move money. `recommendation` must equal `policy_result.decision`; the application uses the engine value.
2. The model never produces card controls. Any control-shaped output field rejects the whole response.
3. Card controls are derived only from a passport that validates as `VALID` at the supplied time and key.
4. Card control arrays are never empty. Currency and MCC are checked against trusted allowlists.
5. The approved amount is the per-transaction cap and the cumulative cap.
6. Approval is bound to the exact seven fields plus proposal ID. Changing a term invalidates both the approval token and the passport.
7. Record status, expiry and approval ID are sealed; tampering is `INVALID`, not silently accepted.
8. `FAILED_TERMINAL` requires GET-confirmed terminal state.
9. A changed fingerprint for an existing retry operation is rejected.
10. Expected inflows are excluded from the confirmed case; expected outflows always count.

## Passport status precedence

```text
INVALID  -> malformed record, bad seal, bad stored terms, bad status
MISMATCH -> valid seal, but expected intent hash differs
EXPIRED  -> valid seal and matching intent, but now >= expiry
VALID    -> all checks pass
```

This ordering ensures a tampered record cannot be reported as merely expired, and a mismatched record cannot be reported as merely expired.

## Threat model (prototype scope)

| Threat | Mitigation | Residual risk |
|---|---|---|
| Prompt injection in a quote | Prompt boundary + injection scanner + model output validation; text never reaches controls | A model may still produce misleading prose; human reviews exact terms |
| Model invents a card limit | Validator rejects control fields; controls derive from passport only | None in code path |
| Human approves different terms than displayed | Approval token binds proposal ID + exact intent; passport hash binds seven fields | UI/API compromise out of scope |
| Stored passport tampering | Record seal over all fields; intent hash over terms | Key management is environment-level |
| Duplicate request after timeout | SQLite retry registry replays one request ID; fingerprint change rejected | Live Airwallex retry semantics UNCONFIRMED |
| Cents-for-dollars error | `max_amount` ceiling in control derivation | Config must set a sensible ceiling |
| Cross-origin dashboard write | Localhost bind + Origin check | Not a production CSRF defence |
| Secret leakage | Passport key from env or generated per process; no credentials in prompt | Demo uses synthetic data only |

## Why the model is not the decision-maker

The model is good at reading arbitrary vendor language. It is not a ledger, a clock, a policy engine, or a signing authority. Mandate keeps it on the unstructured side of the boundary and makes every money-relevant step deterministic, testable and sealed.
