# Submission note

## Product thesis

This product chooses subtraction over attention-manufacturing. It turns a raw
feed of candidate signals into at most `BRIEF_MAX_ITEMS` prioritized ones by
removing corporate-action artefacts, market-wide repetition, sector
duplicates, and candidates below the attention cap. The output is a reading
register, not a stream of prompts. Live conservation of that funnel — how
many candidates were evaluated versus surfaced, computed from the real
persisted replay window, not a fixed example — is at `/eval` and
`GET /api/eval/funnel`.

## Register architecture

`<Register>` is structural, not decorative:

- **Terminal** is high-density market reality: tabular monospace figures and
  directional hues for price movement.
- **Dispatch** is an editorial reading room: Source Serif prose and monochrome
  confidence colours for final, provisional, and stale judgement.

The context prevents a Dispatch child from accidentally emitting Terminal
direction colours.

## Quantitative and calendar invariants

- The cursor uses a 17-session decay multiplier anchored to Wednesday 12 August
  2026. Session distance follows real exchange sessions rather than calendar-day
  arithmetic.
- Muhurat and special sessions widen day membership through 23:59:59 IST. This
  respects circular-governed session dates without inventing a close time.
- The funnel conserves every candidate: evaluated − (corporate action +
  market-wide + sector-wide + below-cap) = surfaced, enforced by
  `DeliveryBudgetBlock.verify_invariants()` on every request and replayed
  across the full evaluation window by `app/eval/replay_runner.py`.

## Evaluator zero-friction flow

Open `/login`, choose **Open the demo account**, and the seeded state opens
directly at `/brief`. The application runs offline with synthetic market data
and uses the Saturday 5 September 2026 baseline. No broker credentials, Docker,
Redis, or external gateway are required.

## One-command verification

```powershell
Set-Location frontend
npm run verify
```

This checks JavaScript-only extensions, prohibited copy and token purity, runs
the unit tests, builds production output, and verifies emitted fonts and chunks.

## Clean archive

From the repository root, create the evaluator archive while excluding local
dependencies, generated output, caches, secrets, and operating-system files:

```powershell
$exclude = '\\(node_modules|dist|.mypy_cache|.pytest_cache|.ruff_cache|.git)($|\\)|(^|\\)(.env)$|Thumbs.db$|\\.DS_Store$'
Get-ChildItem -Recurse -File |
  Where-Object { $_.FullName -notmatch $exclude } |
  Compress-Archive -DestinationPath .\groww-watchlist-submission.zip -Force
```

`.env.example` is retained because the exclusion matches `.env` exactly.
