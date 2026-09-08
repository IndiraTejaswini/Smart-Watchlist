# Broker API access — the decision

**BUILD_PLAN task 0.2. Status: decided — ship with the polling fallback.**
**Date: 6 September 2026.**

Task 0.2 accepts either credentials in `.env` or a written decision to ship on
the polling fallback. This is that decision.

## The decision

`QUOTE_SOURCE=POLLING` is the shipped default. `PollingSource` is the quote
source the demo runs on. `BrokerWebSocketSource` remains in the design and
behind the same `QuoteSource` protocol (docs/BUILD_SPEC.md §14.1), so a broker feed
is a configuration change if credentials appear later.

## Why

Every Indian broker developer programme — Kite Connect, Upstox, Dhan,
Angel One SmartAPI, ICICI Breeze — issues API credentials only against a funded,
KYC-verified brokerage account belonging to a real identified person. Some also
carry a monthly subscription for the API app. That is not a registration a
coding agent can complete on someone's behalf: it needs the account holder's
identity documents, their demat account, and in some cases their payment
instrument.

So the choice was never "register or fall back". It was: block Phase 0 on a
human action with a stated activation latency of up to 24 hours, or take the
fallback that the architecture already specifies and treat a broker feed as an
upgrade. §14.1 is explicit that the abstraction exists precisely so this is a
config change — *"if activation takes 24 hours you lose a third of the budget"*.
Blocking here would spend the exact budget the abstraction was designed to
protect.

## What the fallback costs

| | Broker websocket | Polling fallback |
|---|---|---|
| Update cadence | Push, sub-second | `POLL_INTERVAL_SECONDS` (=5) |
| Freshness states reachable | All of §14.2 | All of §14.2 |
| Conflation (§14.3) | Load-bearing | Still correct, less often loaded |
| Depth / order book | Available | Not available — not used by this system |

The honest cost is cadence, and it is smaller than it looks for this product.
The Brief is an attention allocator with a five-item budget, not a trading
terminal. Signals are evaluated every `SIGNAL_EVAL_INTERVAL_SECONDS` (=30) for
subscribed symbols and never per raw tick (§4.2), so a 5-second quote cadence
sits well inside the resolution the signal engine actually consumes. What
degrades is the live price ticking on screen, not what the system detects.

Two things the fallback does **not** compromise:

- **The freshness state machine still works.** `DELAYED_S` (=15) is three poll
  intervals, so a stalled poller is visible as `DELAYED` rather than silently
  showing a stale price. R5 holds.
- **The benchmark anchor still works.** §14.2 requires always subscribing to an
  index or a guaranteed-liquid proxy so a market-wide halt can be distinguished
  from a dead feed. Polling that anchor is the same triangulation.

## How to switch, if credentials arrive

1. Register with the broker, create an API app, obtain the key and secret.
2. Put them in `.env`:
   ```
   QUOTE_SOURCE=BROKER_WS
   BROKER_API_KEY=...
   BROKER_API_SECRET=...
   BROKER_ACCESS_TOKEN=...
   ```
3. Restart `backend-feed`. No code change, no migration, no rebuild.

The `QuoteSource` protocol (`subscribe`, `unsubscribe`, `stream`,
`heartbeat_age_seconds`) is the entire contract either implementation has to
satisfy, and the freshness machine, conflator and WS gateway consume only that.

## What goes in the README

This is a documented limitation, not a hidden one. The README states that the
demo runs on a 5-second polling quote source, that a broker websocket is a
config change behind `QuoteSource`, and why — the same reason §2.2 documents BSE
and derivatives as out of scope rather than pretending they were never
considered.

## If you do want a broker feed

This needs you, not the agent. Pick one broker, register with your own KYC, and
paste the credentials into `.env`. Angel One SmartAPI and Dhan have historically
had the lowest friction for a personal developer account; verify current pricing
and approval turnaround at signup rather than trusting any figure quoted here.
Nothing else in the build depends on the answer.
