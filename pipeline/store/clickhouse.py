"""
pipeline.store.clickhouse — insert Records into the ClickHouse `records` table.

We use the `clickhouse-connect` library which is pure Python (no C driver
needed).  It communicates over the HTTP interface on port 8123.

Batch insertion strategy:
  - Records are inserted in chunks of BATCH_SIZE (1000 rows).
  - Each chunk is a single INSERT ... FORMAT JSONEachRow call.
  - Chunking prevents hitting ClickHouse's default max_query_size limit and
    keeps memory usage bounded for large bhavcopy loads (~8000 rows/day).

Deduplication:
  - The `records` table uses ReplacingMergeTree(fetched_at).
  - If the same (source, series, dimension, date) is inserted again (e.g. a
    revised GDP figure), ClickHouse will keep the row with the latest
    fetched_at during background merges.
  - Always query with FINAL to get the deduplicated view.
"""

from typing import TYPE_CHECKING

import clickhouse_connect
import structlog

from pipeline.schema.record import Record

if TYPE_CHECKING:
    from clickhouse_connect.driver.client import Client

log = structlog.get_logger()

BATCH_SIZE = 1000
TABLE = "records"


def get_client(
    host: str,
    port: int = 8123,
    database: str = "indiafindata",
    username: str = "default",
    password: str = "",
) -> "Client":
    """
    Create and return a ClickHouse client.

    Call this once at startup and reuse the client.  clickhouse-connect
    clients are thread-safe and maintain a connection pool internally.

    Args:
        host:     ClickHouse hostname (e.g. "localhost" or "clickhouse" in Docker)
        port:     HTTP interface port (default 8123)
        database: Database name (default "indiafindata")
        username: ClickHouse user (default "default")
        password: ClickHouse password (empty string for no password)

    Returns:
        A connected clickhouse_connect Client instance.
    """
    return clickhouse_connect.get_client(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
    )


def insert_batch(client: "Client", records: list[Record]) -> int:
    """
    Insert a list of Records into ClickHouse in BATCH_SIZE chunks.

    Args:
        client:  A connected ClickHouse client (from get_client()).
        records: Records to insert.  Empty list is a no-op.

    Returns:
        Number of rows inserted (= len(records) on success).

    Raises:
        Exception: re-raised after logging if any batch insert fails.
                   The caller (scheduler job) catches this and marks the
                   pipeline_runs row as 'failed'.

    Why JSON format?
        clickhouse-connect's insert() method handles serialisation.  We pass
        column names + row data explicitly which is cleaner than JSONEachRow
        strings but equivalent in effect.
    """
    if not records:
        return 0

    # ClickHouse column names and order (must match the table DDL in migrate.sql)
    columns = [
        "source", "series", "dimension", "value", "date",
        "granularity", "unit", "region", "tags", "fetched_at",
    ]

    total_inserted = 0

    # Split into chunks to avoid hitting ClickHouse memory/size limits
    for chunk_start in range(0, len(records), BATCH_SIZE):
        chunk = records[chunk_start : chunk_start + BATCH_SIZE]

        # Build list-of-lists row data in column order
        rows = [
            [
                r.source,
                r.series,
                r.dimension,
                r.value,
                r.date,           # clickhouse-connect handles date → string conversion
                r.granularity,
                r.unit,
                r.region,
                r.tags,           # dict[str,str] → ClickHouse Map(String, String)
                r.fetched_at,     # datetime → ClickHouse DateTime
            ]
            for r in chunk
        ]

        client.insert(TABLE, rows, column_names=columns)
        total_inserted += len(chunk)

        log.debug(
            "clickhouse.insert_chunk",
            table=TABLE,
            chunk_size=len(chunk),
            total_so_far=total_inserted,
        )

    return total_inserted


def table_exists(client: "Client") -> bool:
    """
    Return True if the `records` table exists in the configured database.

    Used at startup to verify migrations have been applied before the
    scheduler starts firing jobs.
    """
    result = client.query(
        "SELECT count() FROM system.tables WHERE database = currentDatabase() AND name = 'records'"
    )
    return bool(result.first_row[0])
