#!/usr/bin/env bash
# scripts/seed.sh — one-time setup: apply migrations + backfill 5 years of Phase 1 data.
#
# Run after `docker compose up -d` once all services are healthy.
# This script is IDEMPOTENT — safe to re-run.
#
# Usage:
#   bash scripts/seed.sh
#   bash scripts/seed.sh --from 2015-01-01   (custom start date)

set -euo pipefail

FROM_DATE="${1:---from}"
if [[ "$FROM_DATE" == "--from" ]]; then
    # Default: 5 years ago from today
    FROM_DATE=$(date -d "5 years ago" +%Y-%m-%d 2>/dev/null || date -v-5y +%Y-%m-%d)
else
    FROM_DATE="$2"
fi

echo "=== india-findata seed ==="
echo "Backfill from: $FROM_DATE"
echo ""

# 1. Apply ClickHouse schema
echo "--- Applying ClickHouse schema ---"
# Split the migrate.sql: ClickHouse statements come before the PostgreSQL section.
# We extract up to the PostgreSQL header comment.
CLICKHOUSE_SQL=$(sed -n '/^-- -----/,/^-- POSTGRESQL/{ /^-- POSTGRESQL/q; p }' scripts/migrate.sql)

curl -s -u "${CLICKHOUSE_USER:-default}:${CLICKHOUSE_PASSWORD:-}" \
     "http://${CLICKHOUSE_HOST:-localhost}:${CLICKHOUSE_PORT:-8123}/" \
     --data-binary "$CLICKHOUSE_SQL"
echo "ClickHouse schema applied."

# 2. Apply PostgreSQL schema
echo ""
echo "--- Applying PostgreSQL schema ---"
# Extract PostgreSQL statements (from the POSTGRESQL section to end of file)
POSTGRES_SQL=$(sed -n '/^CREATE TABLE IF NOT EXISTS pipeline_runs/,$ p' scripts/migrate.sql)

PGPASSWORD="${POSTGRES_PASSWORD:-findata_dev}" psql \
    -h "${POSTGRES_HOST:-localhost}" \
    -p "${POSTGRES_PORT:-5433}" \
    -U "${POSTGRES_USER:-findata}" \
    -d "${POSTGRES_DB:-indiafindata}" \
    -c "$POSTGRES_SQL"
echo "PostgreSQL schema applied."

# 3. Backfill all Phase 1 sources
echo ""
echo "--- Backfilling all Phase 1 sources from $FROM_DATE ---"
python -m scripts.backfill --all --from "$FROM_DATE"

echo ""
echo "=== Seed complete ==="
