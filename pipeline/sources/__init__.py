"""
pipeline.sources — one module per data source.

Each module exports a class that inherits from Source (base.py) and
implements fetch() + backfill().  The scheduler imports these classes
and calls fetch() on each scheduled run.

Phase 1 sources (this codebase):
  mospi.py       — MOSPI CPI, IIP, GDP via api.mospi.gov.in
  data_gov_in.py — RBI policy rates, banking data via api.data.gov.in

Phase 2 (future):
  nse.py         — NSE bhavcopy CSV (daily equity EOD)
  bse.py         — BSE bhavcopy CSV

Phase 3 (future):
  rbi.py         — RBI DBIE Excel/HTML (forex reserves, M3, credit)
"""
