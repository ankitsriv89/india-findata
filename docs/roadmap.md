# india-findata — Roadmap

## Phase 1 — Macro Foundation (start here)

**Goal**: get the pipeline running end-to-end with clean, official-API sources.

Sources:
- MOSPI CPI (monthly) — official API, clean JSON, easiest to start
- MOSPI IIP (monthly) — same API
- MOSPI GDP (quarterly) — same API
- data.gov.in (weekly/monthly) — REST API, RBI policy rates, banking aggregates

Dashboard:
- CPI timeline (YoY % change, last 5 years)
- Repo rate step chart with RBI meeting annotations
- GDP quarterly growth bar chart
- IIP sector breakdown

**Why start here**: official APIs, no scraping, clean structured JSON. Validates the full
pipeline stack (scheduler → fetch → normalize → ClickHouse → FastAPI → React) before
tackling harder sources.

---

## Phase 2 — Markets Layer

**Goal**: add daily market data — highest-value addition for most users.

Sources:
- NSE bhavcopy CSV (daily EOD prices, all equities)
- BSE bhavcopy CSV (same, BSE listed)
- NSE FII/DII daily data

Dashboard additions:
- NIFTY50 / SENSEX price line chart
- FII/DII net daily flows (bar chart) overlaid with NIFTY
- Top 10 gainers/losers table
- Sector heatmap (% change, D3 grid)

**Key challenge**: NSE bhavcopy ZIP contains ~2000 symbols × 4 dimensions = ~8000 Records/day.
Validate the batch insert pipeline handles this volume cleanly.

---

## Phase 3 — Banking & Credit (RBI DBIE)

**Goal**: add the macro-credit layer — most complex source due to irregular Excel/HTML formats.

Sources:
- RBI Weekly Statistical Supplement (Excel) — forex reserves, money market rates
- RBI DBIE — M3 money supply, bank credit growth by sector
- RBI NPA data (quarterly, PDF) — may need pdfplumber

Dashboard additions:
- Forex reserves (USD billion) weekly line
- Bank credit growth vs GDP overlay
- M3 / monetary aggregates chart

**Risk**: RBI DBIE pages and Excel layouts change without notice. Build defensively —
log + skip unknown columns rather than crashing.

---

## Phase 4 — Cross-domain Analytics

**Goal**: surface the interesting correlations between macro, markets, and credit data.

Analytics:
- CPI vs repo rate: did rate hikes dampen inflation? (lag analysis)
- FII inflows vs INR/USD rate correlation
- IIP sector production vs NSE sectoral index returns
- Credit growth vs GDP growth (leading indicator?)

Dashboard additions:
- Correlation panel: pick any two series, overlay on dual-axis chart, show Pearson r
- Annotation layer: mark RBI policy dates, budget dates, election results on charts

---

## Future ideas

- **AMFI monthly MF data**: mutual fund category flows and AUM — straightforward CSV
- **CMIE / CapEx data**: corporate investment cycles — requires paid subscription
- **INR/USD daily**: from RBI reference rates (free, daily)
- **India VIX**: NSE volatility index — available in bhavcopy
- **State-level data**: RBI state finances report (annual)
- **Real-time alerts**: notify (webhook/email) when CPI release or RBI policy decision is published
