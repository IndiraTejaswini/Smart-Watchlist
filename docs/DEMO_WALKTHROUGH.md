# Jury walkthrough

This runbook is designed for a clean, zero-credential evaluation. Start the
frontend with `npm run dev` from `frontend`, then follow the route sequence.

## 1. Landing — `/`

Observe the subtraction hero on mount. It runs once over 2.5 seconds: roughly 40
ticker rows collapse to exactly three remaining items and a quiet line. Reloading
does not create a loop; reduced-motion mode presents the final state immediately.

## 2. Demo login — `/login`

Click **Open the demo account**. No external credentials are needed. The seeded
cursor and watchlist are loaded and the app navigates directly to `/brief`.

## 3. Dispatch brief — `/brief`

Verify the editorial 66ch measure, hairline separators, and absence of cards or
container boxes. Direction is not communicated with red or green. Open an item’s
quiet **why this?** control and inspect the explain request at
`/api/brief/explain/{id}`.

## 4. Cursor spine — §3

Drag the cursor back to 12 August 2026. Observe the 220ms restack as the reading
period changes. The session axis skips weekends and holidays rather than filling
them with invented points.

## 5. Terminal overview — `/overview`

Inspect the three benchmark cards, the equal-weight watchlist chart rebased to
100, and its amber cursor marker. Check the reconciled attention budget:
41 evaluated, 2 corporate action, 11 market-wide, 4 sector-grouped, 20 below
the cap, and 4 shown.

## 6. Live watchlist — `/watchlist/wl_demo`

Scroll the 250-row virtualized table and inspect the viewport-scoped quote activity.
Prices update in place with no green or red row flash, pulse, or fade. Confirm
the freshness dot, symbol, last price, change, percentage, turnover, delivery,
and 20-session range sparkline columns.

## 7. Symbol detail — `/symbol/IDEA`

Toggle **As traded**. Compare the as-traded and adjusted candlestick series and
the engine marks. The corporate-action adjustment demonstrates why an apparent
price discontinuity is suppressed rather than dispatched as a regular signal.

## 8. Evaluation — `/eval`

Inspect the stepped funnel, the side-by-side suppression comparison, the
explained versus unexplained five-session continuation table, parser coverage,
and the five written self-audit cases.

## 9. Settings — `/settings`

Review the cursor control, the attention safety cap, and the provenance table
with source, last ingest timestamp, and row count.

## Verification commands

```powershell
Set-Location frontend
node scripts/check-prohibitions.mjs
npm test
npm run build
```
