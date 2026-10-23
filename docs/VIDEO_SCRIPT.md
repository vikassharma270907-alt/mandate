# 5-minute video walkthrough script

**Target runtime: 4:45.** Screen recording, 1080p, no live sandbox claim. If the live sandbox has not been verified, say so on screen.

**Live demo:** https://mandate-vercel.vercel.app

Open with the dashboard already running:

```powershell
python -m mandate serve
```

Keep the terminal and browser windows at readable zoom. The dashboard copy already labels the build **SANDBOX**, **SYNTHETIC DATA** and **DEMO EXTRACTOR**.

---

## Scene 1 — Problem and architecture (0:00–0:35)

**On screen:** dashboard hero, balance panel (`$32,000`, floor `$15,000`, expected receipt `$12,000 at week 4`), then the architecture panel or README diagram.

**Narration:**

> "A founder has a $32,000 balance and a $15,000 reserve floor. CloudMetrics costs $2,000 a month, or $19,680 a year. Annual saves $4,320 — but paying it now leaves $12,320, which breaks the floor before a $12,000 customer receipt lands.
>
> The hard part is not reading the quote. It is keeping the language model away from the money. Mandate puts the math in a deterministic engine, the documents in an untrusted box, and the limits in the card."

**Lower third:** `Trust boundary: model reads · engine decides · human approves · card enforces`

---

## Scene 2 — The deterministic engine (0:35–1:30)

**On screen:** terminal.

```powershell
python -m mandate scenarios
```

Let the nine-row table land. Point at rows 1–4 and 7–9.

**Narration:**

> "This is not a prompt with a calculator. The engine is side-effect free and tested against nine scenarios. Watch the same quote change its answer.
>
> At $32,000 with the receivable expected at week 4, annual drops the confirmed minimum to $12,320 at week zero — $2,680 below the floor. Monthly stays at $26,000. The engine selects monthly.
>
> At $34,680, annual lands exactly on $15,000 and is safe. At $34,679.99 — one cent lower — it is not. At $20,000, both plans breach, and the only correct answer is DEFER.
>
> The conservative case excludes expected inflows but always counts expected outflows. Within a week, outflows are applied and the minimum is checked before inflows. Money is strict Decimal; no floats, no exponents, no sub-cent surprises."

**Cut to:** `python -m mandate test` (optional 5-second clip, or show the 120-test summary from the README).

**Lower third:** `47 engine tests · 120 tests total · all passing`

---

## Scene 3 — Decision, approval and enforcement (1:30–3:10)

**On screen:** dashboard. Click **Run the policy engine**.

**Narration:**

> "The engine returns monthly. The agent reads the vendor quote, extracts the terms with sources and confidence, and echoes the engine decision. Its JSON is validated. It cannot set a limit, and it cannot overrule the policy."

Point at the annual and monthly plan cards, the chart, the `ENGINE PICK` badge, and the agent boundary line.

**Click Approve & issue card.**

**Narration:**

> "The human approves seven exact fields: vendor, amount, currency, cadence, merchant category, evidence reference and policy version. The application seals them with HMAC-SHA256 into a Decision Passport, derives card controls from the passport, and creates the card."

Point at the passport hashes and the card controls: `MULTIPLE`, `$2,000` per transaction, `$2,000` monthly, USD, MCC 5734.

**Click Try annual $19,680.**

**Narration:**

> "The card declines the annual charge. The reason is the per-transaction limit, not a model opinion. The prompt never sees a card-control field."

**Click Try monthly $2,000.**

> "The monthly charge is approved. This is an authorization-only sandbox simulation; no funds move."

**Click Land receipt.**

**Narration:**

> "The $12,000 receivable lands. Available cash is now $44,000. The pending proposal is marked stale — the old approval cannot bind to the new cash position."

**Click Re-run engine.**

Point at the new `PROPOSE_ANNUAL` result and the passport mismatch badge.

> "The same quote now selects annual. Annual leaves $24,320 and saves $4,320 a year. The old monthly card still declines the $19,680 charge. A new decision requires a fresh human approval and a fresh passport."

Optionally click **Approve & issue card** and try the annual card, showing it approved and single-use.

**Lower third:** `Same quote → different decision → fresh approval → fresh card`

---

## Scene 4 — Edge cases and safeguards (3:10–4:10)

**On screen:** Security lab in the right rail.

**Click Prompt-injection quote.**

> "The second document contains 'ignore previous instructions', a demand to set the card limit to $10 million, and a request to export the API key. The scanner flags every instruction as data. The policy decision and card limit are unchanged."

**Click Tamper with passport.**

> "Changing the approved amount by $100 invalidates the record. The intent hash and record seal both fail, and the status is INVALID — not expired, not valid."

**Click Retry same request ID.**

> "The retry registry mints one request ID for one logical operation. A retry replays that same ID. A terminal failure can only be recorded after a GET confirms it, and then the operation is closed."

**Click Re-check on Plan re-check.**

> "The live-plan check is recommend-only: HOLD or recommend freeze and escalate. It never freezes a card or moves money."

**Lower third:** `INVALID before MISMATCH before EXPIRED · 16-thread retry race · injection ignored as data`

---

## Scene 5 — Summary and code (4:10–4:45)

**On screen:** README architecture diagram, then repository layout, then the test summary.

**Narration:**

> "Mandate is a sandbox prototype, not production banking software. The policy engine, passport, card controls and retry registry are deterministic and covered by 120 tests. The model is confined to extraction and explanation. The card, not the prompt, enforces the limits.
>
> The live Airwallex adapter is present but unconfirmed until the one-hour sandbox run is executed and captured. The repo includes the runbook, the prompt, the fixtures and the full walkthrough.
>
> Cash decides. The card enforces. The model only reads."

**End card:**

```text
github.com/vikassharma270907-alt/mandate
python -m mandate serve
Sandbox prototype · synthetic data · not production banking software
```

---

## Recording checklist

- [ ] Dashboard at 100% zoom, 1440×900 or larger.
- [ ] Terminal font at least 14pt; `python -m mandate scenarios` visible.
- [ ] Start from a reset demo (`Reset demo`) so the first decision is monthly.
- [ ] Close notifications and any real credentials.
- [ ] Keep each click deliberate; the script has 35 seconds of slack.
- [ ] Do not say "live Airwallex" unless the live runbook has been completed and captured.
- [ ] Show the `SANDBOX` and `SYNTHETIC DATA` labels at least twice.
- [ ] Export at 1080p, under 5:00.

## If a live sandbox run is verified

Replace the Scene 3 card creation and authorization clip with the live sandbox evidence from [`SANDBOX_RUNBOOK.md`](SANDBOX_RUNBOOK.md). Keep the fake-sandbox clip as a fallback and label both clearly. Do not mix live and synthetic frames without a caption.
