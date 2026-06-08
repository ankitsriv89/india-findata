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
