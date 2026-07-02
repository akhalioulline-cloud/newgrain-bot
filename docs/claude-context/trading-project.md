---
name: trading-project
description: Separate parallel project — a systematic crypto trading learning sandbox in ~/trading
metadata: 
  node_type: memory
  type: project
  originSessionId: 9f18930a-812a-4bdb-8d4b-0255562b4ca9
---

A **second, separate project** (dir `~/trading`, own git repo) the founder runs in
parallel to Flagleaf/NewGrain. Goal: learn systematic/algorithmic trading and find
workable strategies. NOT true HFT — the hardware (Mac mini/MacBook Air, average home
connection, ~20–100ms latency) rules out latency-competitive HFT entirely; framed as
mid/low-frequency systematic trading instead.

Decisions made (2026-07-02):
- **Crypto only, no MOEX for now.** Data via **OKX public API** — chosen because
  Binance (451) and Bybit (403) are **geoblocked from the founder's connection**;
  OKX + data.binance.vision are reachable. No API key needed for candle downloads.
- Starting capital ~**$1000**, educational — expects to roughly break even; the point
  is learning, not returns.

Toolkit built (all paper/no-real-orders): `fetch_data.py` (OKX candles→CSV),
`engine.py` (shared simulator: positions→equity+costs+metrics), `strategies.py`
(`meanrev` z-score mean-reversion + `trend` MA-crossover, with a registry+param grids),
`backtest.py`, `robustness.py` (in-sample/out-of-sample split + param sweep + cross-asset;
ranks only combos that actually trade so "do nothing" can't win), `paper_trade.py`
(live fake-$1000 loop vs OKX, resumable via JSON state + CSV ledger),
`fetch_funding.py` + `funding_arb.py` (market-neutral funding-rate carry: spot long +
perp short, unlevered, income−fees, enter/exit APR thresholds), `regime.py` (dashboard:
Kaufman Efficiency Ratio trend-strength + vol + funding backdrop → recommends matched
strategy or CASH, cross-checked vs recent realised returns).

Core lesson surfaced repeatedly: every strategy has a SEASON. Over the ~3-month test
window (flat/low-funding) all three bled; but the recent ~21d is choppy → mean-reversion
is the matched, currently-working one (regime.py + reality check agree). Funding is in a
LOW regime now (BTC/ETH ~+1-2% APR), so carry is dormant, not broken.

Teaching stance to keep: emphasize NET-after-costs (fees+slippage ~0.15% one-way in the
model), beating buy-and-hold, and overfitting as the #1 trap. Same non-technical-founder
approach as [[user-nontechnical-founder]] / [[workflow-decisions-vs-code]].

Next options discussed: more robustness sweeps, a 3rd strategy (pairs/funding-rate arb),
harden the paper→live gate before any real money.
