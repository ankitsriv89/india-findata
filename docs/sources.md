# Data Source Catalogue

All Phase 1 data sources, their fields, cadence, and example values.

---

## MOSPI CPI — Consumer Price Index

| Field | Value |
|-------|-------|
| Source name | `mospi_cpi` |
| Series | `CPI_GENERAL`, `CPI_FOOD`, `CPI_RURAL`, `CPI_URBAN` |
| Dimension | `index_value` |
| Granularity | monthly |
| Unit | `index_points` (base year 2012=100) |
| Region | `india` |
| API | `https://api.mospi.gov.in/cpi` |
| Release schedule | 12th of each month at 5:30 PM IST, for previous month |
| Tags | `base_year: "2012"`, `release: "provisional"/"final"` |

**Example value**: CPI General = 190.3 for January 2024 means the general price level is 90.3% higher than the 2012 base.

**YoY inflation**: computed client-side: `(current - prev_year) / prev_year × 100`. For Jan 2024 vs Jan 2023: if CPI was 177.5 in Jan 2023, inflation = `(190.3 - 177.5) / 177.5 × 100 = 7.2%`.

---

## MOSPI IIP — Index of Industrial Production

| Field | Value |
|-------|-------|
| Source name | `mospi_iip` |
| Series | `IIP_GENERAL`, `IIP_MANUFACTURING`, `IIP_MINING`, `IIP_ELECTRICITY` |
| Dimension | `index_value` |
| Granularity | monthly |
| Unit | `index_points` (base year 2011-12=100) |
| Region | `india` |
| Release schedule | 12th of each month at 4:00 PM IST, with **2-month lag** |
| Tags | `base_year: "2011-12"`, `release: "provisional"/"final"` |

**Note**: IIP for April is released in mid-June. The most recent 2 months in your database will always be missing — this is normal.

---

## MOSPI GDP — Gross Domestic Product

| Field | Value |
|-------|-------|
| Source name | `mospi_gdp` |
| Series | `GDP_GROWTH_RATE` |
| Dimension | `yoy_change_pct` |
| Granularity | quarterly |
| Unit | `percent` |
| Region | `india` |
| API | `data.gov.in` (resource ID: verify at runtime) |
| Release schedule | ~60 days after quarter end |
| Tags | `base_year: "2011-12"`, `release: "provisional"/"final"` |

**Fiscal quarters**: India's fiscal year starts April 1.
- Q1: April–June → stored as `YYYY-04-01`
- Q2: July–September → stored as `YYYY-07-01`
- Q3: October–December → stored as `YYYY-10-01`
- Q4: January–March → stored as `YYYY-01-01` (of calendar year after FY start)

---

## RBI Rates — Policy Interest Rates

| Field | Value |
|-------|-------|
| Source name | `rbi_rates` |
| Series | `REPO_RATE`, `REVERSE_REPO_RATE` |
| Dimension | `rate_pct` |
| Granularity | `daily` (but only changes on MPC meeting dates) |
| Unit | `percent` |
| Region | `india` |
| API | `data.gov.in` (RBI repo rate history resource) |
| Release schedule | Weekly refresh (dataset is small, ~50 rows) |
| Tags | `type: "policy_rate"` |

**Note**: One row per rate change event, not per calendar day. Display with a step chart (type="stepAfter"). The RBI holds ~6 MPC meetings per year.

**Example**: Repo rate was 6.50% from Feb 2023 to Jun 2024.

---

## RBI Forex — Foreign Exchange Reserves

| Field | Value |
|-------|-------|
| Source name | `rbi_forex` |
| Series | `FOREX_RESERVES` |
| Dimension | `total_usd_bn` |
| Granularity | weekly |
| Unit | `USD_billion` |
| Region | `india` |
| API | `data.gov.in` (RBI forex reserves resource) |
| Release schedule | Weekly, published every Friday |
| Tags | `published_by: "rbi"` |

**Example**: India's forex reserves were ~$650 billion in mid-2024. These reserves let RBI intervene in currency markets to defend the INR.

---

# Phase 2 — Markets Layer

## NSE Bhavcopy — Equity End-of-Day (OHLC + Volume)

| Field | Value |
|-------|-------|
| Source name | `nse_bhavcopy` |
| Series | One per symbol (e.g. `TCS`, `RELIANCE`, `INFY`) |
| Dimension | `open_price`, `high_price`, `low_price`, `close_price`, `volume` |
| Granularity | `daily` |
| Unit | `INR` (prices), `shares` (volume) |
| Region | `india` |
| API | `archives.nseindia.com` — public ZIP-compressed CSV bhavcopy |
| Release schedule | Daily after market close (~7 PM IST), Mon–Fri |
| Tags | `exchange: "NSE"`, `isin`, `series: "EQ"` |

**Quirks**: file is a ZIP containing one CSV; we unzip in-memory. Only `SERIES == "EQ"`
rows are kept (BE/BL/GS settlement series are dropped). Suspended scrips have blank
prices — those rows are skipped, never inserted as NaN. ~2000 symbols × 5 dimensions
≈ 10k records/day, chunked into ~10 inserts of 1000.

**URL pattern**: `…/EQUITIES/<YYYY>/<MON>/cm<DD><MON><YYYY>bhav.csv.zip`
(e.g. `cm02JUN2026bhav.csv.zip`).

## BSE Bhavcopy — Equity End-of-Day

| Field | Value |
|-------|-------|
| Source name | `bse_bhavcopy` |
| Series | One per symbol (`SC_NAME`) |
| Dimension | `open_price`, `high_price`, `low_price`, `close_price`, `volume` |
| Granularity | `daily` |
| Unit | `INR` / `shares` |
| Region | `india` |
| API | `bseindia.com/download/BhavCopy/Equity` — public ZIP CSV |
| Release schedule | Daily after close, Mon–Fri |
| Tags | `exchange: "BSE"`, `isin`, `sc_code`, `group` |

**Quirks**: BSE uses different column names (`SC_NAME`/`SC_GROUP`/`NO_OF_SHRS`) than NSE.
Equity rows are those whose `SC_GROUP` is an equity group (A/B/T/Z/M/X…); debt/derivative
groups are dropped. URL date is `DDMMYY` (e.g. `EQ_ISINCODE_020626.ZIP`).

## FII/DII — Institutional Net Equity Flows

| Field | Value |
|-------|-------|
| Source name | `fii_dii` |
| Series | `FII_NET_EQUITY`, `DII_NET_EQUITY` |
| Dimension | `net_flow` |
| Granularity | `daily` |
| Unit | `crore_INR` |
| Region | `india` |
| API | NSE FII/DII report CSV (published on behalf of SEBI) |
| Release schedule | Daily ~7:30 PM IST, Mon–Fri |
| Tags | `category` (raw report label) |

**Quirks**: net flow may be **negative** (net selling) — that's valid data, not an error,
so the validator rejects only missing/non-numeric values, never the sign. The live URL is
fragile (may require session cookies / move); the source is best-effort — a fetch failure
logs and returns nothing rather than crashing the scheduler. Fully fixture-tested offline.

**Example**: On a risk-off day FII might be −1,234 cr (net sell) while DII is +1,035 cr
(net buy), a classic counter-flow pattern.

---

# Phase 3 — Banking & Credit (RBI DBIE)

All four series share `source = "rbi_dbie"`. The RBI DBIE portal has no clean API;
data comes as Excel workbooks (parsed with openpyxl) and one quarterly PDF (parsed
with pdfplumber). Parsing is **defensive** — unknown columns / malformed rows are
skipped with a warning, never crash the job.

## RBI Forex Reserves (DBIE) — `FOREX_RESERVES`

| Field | Value |
|-------|-------|
| Source name | `rbi_dbie` |
| Series | `FOREX_RESERVES` |
| Dimension | `value` |
| Granularity | `weekly` |
| Unit | `USD_billion` |
| API | RBI DBIE Weekly Statistical Supplement (Excel) |
| Release schedule | Weekly, Friday |
| Tags | `publisher: "rbi"`, `via: "dbie"` |

(Distinct from the Phase 1 `rbi_forex` data.gov.in source — different `source` value,
richer DBIE origin.)

## RBI M3 Broad Money — `M3_MONEY_SUPPLY`

| Field | Value |
|-------|-------|
| Source name | `rbi_dbie` |
| Series | `M3_MONEY_SUPPLY` |
| Dimension | `value` |
| Granularity | `monthly` |
| Unit | `crore_INR` |
| API | RBI DBIE money-supply workbook (Excel) |
| Release schedule | Monthly |

**Example**: M3 ≈ ₹245 lakh crore in early 2026 (dashboard shows it in lakh crore).

## Bank Credit Growth — `BANK_CREDIT_GROWTH`

| Field | Value |
|-------|-------|
| Source name | `rbi_dbie` |
| Series | `BANK_CREDIT_GROWTH` |
| Dimension | `value` |
| Granularity | `monthly` |
| Unit | `percent` (YoY) |
| API | RBI DBIE bank-credit workbook (Excel) |

The dashboard overlays this against GDP growth (reuses the Phase 1 `useGDP` hook).

## Gross NPA Ratio — `GROSS_NPA_RATIO`

| Field | Value |
|-------|-------|
| Source name | `rbi_dbie` |
| Series | `GROSS_NPA_RATIO` |
| Dimension | `value` |
| Granularity | `quarterly` |
| Unit | `percent` |
| API | RBI quarterly report (**PDF**, parsed with pdfplumber) |
| Release schedule | Quarterly |
| Tags | `publisher: "rbi"`, `via: "dbie"`, `report: "npa"` |

**Quirks**: extracted from PDF tables via `pdfplumber.extract_tables()`; rows that
aren't a `(quarter_label, numeric_ratio)` pair (headers, totals, "n/a") are skipped.
Quarter labels use Indian-fiscal convention (`Q1 2025-26` → 2025-04-01).

---

# Phase 4 — Cross-domain Analytics (no new source)

Phase 4 adds **no data source** — it is a pure query/compute layer over the data
Phases 1–3 produce. Endpoints:

- `GET /analytics/correlation?source_a=&series_a=&source_b=&series_b=&from=&to=`
  — aligns two existing series by date and returns Pearson r + best-lag + the
  aligned data. Any series in the catalogue (CPI, IIP, GDP, repo rate, forex, M3,
  credit, NPA, FII, DII) can be correlated with any other.
- `GET /analytics/annotations` — curated macro event dates (RBI/budget/election)
  rendered as chart reference lines. Static repo-local list, not a pipeline source.

---

# Macro via MOSPI MCP server (0.5.0) — the live macro layer

CPI, WPI, IIP, and GDP are sourced from the **MOSPI MCP server**
(`mcp.mospi.gov.in`), a JSON-RPC service that serves official MoSPI statistics
with no authentication. This host is reachable from the cloud box (unlike the
IP-filtered `api.mospi.gov.in`), so it is the working macro data path.

| Series | Source name | Dimensions | Granularity | MCP dataset |
|--------|-------------|-----------|-------------|-------------|
| `CPI_GENERAL` | `mospi_cpi` | `index_value`, `yoy_change_pct` | monthly | CPI (base 2012) |
| `WPI_ALL_COMMODITIES` | `mospi_wpi` | `index_value` | monthly | WPI (base 2011-12) |
| `IIP_GENERAL` | `mospi_iip` | `index_value`, `yoy_change_pct` | monthly | IIP (base 2011-12) |
| `GDP` | `mospi_gdp` | `constant_price`, `current_price` | quarterly | NAS indicator 5 |
| `GDP_GROWTH_RATE` | `mospi_gdp` | `yoy_change_pct` | quarterly | NAS indicator 22 |

**Protocol**: POST JSON-RPC `tools/call` (tool `get_data`) → SSE response; the
payload is at `result.content[0].text` (a JSON string) → `{data: [...rows], ...}`.
Tags on every record include `via: "mcp"`. CPI rows also tag `sector`
(Rural/Urban/Combined). The server's `hint` field self-documents valid filters.

**Endpoints**: `GET /macro/cpi`, `/macro/wpi`, `/macro/iip`, `/macro/gdp`
(unchanged names; `/macro/wpi` is new).
