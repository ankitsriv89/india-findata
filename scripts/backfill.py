"""
scripts.backfill — CLI for loading historical data into ClickHouse.

Usage:
  python -m scripts.backfill --source mospi_cpi --from 2015-01-01 --to 2026-06-01
  python -m scripts.backfill --source mospi_gdp --from 2010-01-01
  python -m scripts.backfill --source rbi_rates --from 2000-01-01
  python -m scripts.backfill --source rbi_forex --from 2010-01-01
  python -m scripts.backfill --all --from 2020-01-01

The backfill is IDEMPOTENT — re-running for the same date range is safe.
ClickHouse's ReplacingMergeTree deduplicates on (source, series, dimension, date).

Progress is printed to stdout (one line per source per batch).
Errors abort the backfill for that source but continue with others when --all.
"""

import argparse
import sys
from datetime import date, datetime

import structlog

import pipeline.store.clickhouse as ch_store
import pipeline.store.postgres as pg_store
from pipeline.config import settings
from pipeline.sources.bse import BSEBhavcopySource
from pipeline.sources.data_gov_in import RBIForexSource, RBIRatesSource
from pipeline.sources.mospi import MOSPIGDPSource, MOSPISource
from pipeline.sources.nse import NSEBhavcopySource
from pipeline.sources.sebi import FIIDIISource

log = structlog.get_logger()

# All sources the backfill script knows about (Phase 1 macro + Phase 2 markets)
_SOURCE_NAMES = [
    "mospi_cpi", "mospi_gdp", "rbi_rates", "rbi_forex",
    "nse_bhavcopy", "bse_bhavcopy", "fii_dii",
]


def _build_sources(settings) -> dict:
    """Instantiate all sources keyed by their name."""
    return {
        "mospi_cpi": MOSPISource(
            api_token=settings.mospi_api_token or None,
            datagov_api_key=settings.data_gov_in_api_key or None,
        ),
        "mospi_gdp": MOSPIGDPSource(datagov_api_key=settings.data_gov_in_api_key),
        "rbi_rates": RBIRatesSource(api_key=settings.data_gov_in_api_key),
        "rbi_forex": RBIForexSource(api_key=settings.data_gov_in_api_key),
        # Phase 2 markets — public bulk files, no credentials
        "nse_bhavcopy": NSEBhavcopySource(),
        "bse_bhavcopy": BSEBhavcopySource(),
        "fii_dii": FIIDIISource(),
    }


def _run_backfill(source_name: str, from_date: date, to_date: date, ch_client, pg_pool) -> None:
    """
    Run backfill for one source and log the result to pipeline_runs.

    Args:
        source_name: Key in the _build_sources() dict.
        from_date:   Start of backfill range.
        to_date:     End of backfill range.
        ch_client:   ClickHouse client.
        pg_pool:     psycopg2 pool.
    """
    sources = _build_sources(settings)
    source = sources.get(source_name)
    if source is None:
        print(f"ERROR: unknown source '{source_name}'. Valid: {_SOURCE_NAMES}", file=sys.stderr)
        sys.exit(1)

    job_id = f"backfill_{source_name}_{from_date}_{to_date}"
    run_id = pg_store.start_run(pg_pool, source_name, job_id)

    print(f"[{source_name}] backfilling {from_date} → {to_date} ...")

    try:
        records = source.backfill(from_date, to_date)
        rows_fetched = len(records)
        print(f"[{source_name}] fetched {rows_fetched} records")

        rows_inserted = ch_store.insert_batch(ch_client, records)
        print(f"[{source_name}] inserted {rows_inserted} rows into ClickHouse ✓")

        pg_store.finish_run(
            pg_pool, run_id, source_name,
            rows_fetched=rows_fetched,
            rows_inserted=rows_inserted,
            status="success",
        )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        print(f"[{source_name}] ERROR: {error_msg}", file=sys.stderr)
        pg_store.finish_run(
            pg_pool, run_id, source_name,
            rows_fetched=0,
            rows_inserted=0,
            status="failed",
            error_msg=error_msg,
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill historical data into ClickHouse for india-findata."
    )
    parser.add_argument(
        "--source",
        choices=_SOURCE_NAMES,
        help="Data source to backfill (one of: " + ", ".join(_SOURCE_NAMES) + ")",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_sources",
        help="Backfill all Phase 1 sources",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        required=True,
        metavar="YYYY-MM-DD",
        help="Start date for backfill (inclusive)",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        default=date.today().isoformat(),
        metavar="YYYY-MM-DD",
        help="End date for backfill (inclusive, default: today)",
    )

    args = parser.parse_args()

    if not args.source and not args.all_sources:
        parser.error("Specify --source <name> or --all")

    try:
        from_date = datetime.strptime(args.from_date, "%Y-%m-%d").date()
        to_date = datetime.strptime(args.to_date, "%Y-%m-%d").date()
    except ValueError as exc:
        parser.error(f"Invalid date format: {exc}")

    # Connect to storage
    ch_client = ch_store.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        database=settings.clickhouse_db,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
    )
    pg_pool = pg_store.create_pool(settings.postgres_dsn)

    sources_to_run = _SOURCE_NAMES if args.all_sources else [args.source]
    errors = []

    for source_name in sources_to_run:
        try:
            _run_backfill(source_name, from_date, to_date, ch_client, pg_pool)
        except Exception as exc:
            errors.append((source_name, str(exc)))
            if not args.all_sources:
                # Single-source run: exit on failure
                sys.exit(1)
            # Multi-source: log and continue with remaining sources

    pg_pool.closeall()

    if errors:
        print("\nBackfill completed with errors:", file=sys.stderr)
        for src, err in errors:
            print(f"  {src}: {err}", file=sys.stderr)
        sys.exit(1)

    print("\nBackfill completed successfully.")


if __name__ == "__main__":
    main()
