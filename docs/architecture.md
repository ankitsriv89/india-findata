# Architecture

## System diagram

```mermaid
flowchart TD
    subgraph Sources["External Data Sources"]
        MOSPI["MOSPI MCP server\nmcp.mospi.gov.in\nCPI · WPI · IIP · GDP\n(REST host is IP-filtered)"]
        DATAGOV["data.gov.in API\nRBI rates · forex"]
        NSEBSE["NSE / BSE archives\nbhavcopy ZIP CSV\nOHLC · volume"]
        FIIDII["NSE FII/DII report\nnet equity flows"]
        RBIDBIE["RBI DBIE\ndata.rbi.org.in\nforex · M3 · credit · NPA\nExcel + PDF"]
    end

    subgraph Pipeline["Pipeline Process (single container)"]
        SCHED["APScheduler\nBackground threads"]
        SRC["Sources\nmospi · data_gov_in · nse\nbse · sebi · rbi"]
        STORE["Store\nclickhouse.py\npostgres.py"]
        API["FastAPI\n:8090"]
    end

    subgraph Storage["Storage"]
        CH["ClickHouse\n:8123\nrecords table\nReplacingMergeTree"]
        PG["PostgreSQL\n:5433\npipeline_runs table"]
    end

    subgraph Frontend["Frontend"]
        NGINX["nginx\n:5190"]
        REACT["React SPA\nMacro · Markets · Banking\nCorrelation · Pipeline"]
    end

    subgraph Observability["Observability"]
        PROM["Prometheus\n:9091"]
        GRAF["Grafana\n:3200"]
    end

    MOSPI -->|JSON-RPC/SSE| SRC
    DATAGOV -->|HTTP JSON| SRC
    NSEBSE -->|HTTP ZIP→CSV| SRC
    FIIDII -->|HTTP CSV| SRC
    RBIDBIE -->|HTTP Excel/PDF| SRC
    SCHED -->|fires jobs| SRC
    SRC -->|list[Record]| STORE
    STORE -->|INSERT JSONEachRow| CH
    STORE -->|INSERT/UPDATE| PG
    API -->|SELECT FINAL| CH
    API -->|SELECT| PG
    REACT -->|GET /macro/* · /markets/* · /banking/* · /analytics/*| NGINX
    NGINX -->|proxy_pass| API
    API -->|Prometheus metrics| PROM
    PROM --> GRAF
```

## Key design decisions

### Single-process pipeline + API
FastAPI and APScheduler run in the same Python process. This is intentional for POC scale: one container, no message queue, simple to debug. At production scale you'd separate them.

### ReplacingMergeTree for deduplication
Every data insert is idempotent. Re-running a backfill or re-fetching after a source revision just inserts duplicate rows — ClickHouse deduplicates on `(source, series, dimension, date)` during background merges. Queries use `SELECT ... FINAL` to get the deduplicated view.

### Universal Record schema
All sources normalise to the same `Record` dataclass before insertion. The dashboard and API query layer never need to know which source produced a row — they always query `records FINAL WHERE source = X`.

### PostgreSQL for metadata only
ClickHouse is optimised for analytics, not transactional metadata. Pipeline run history (start time, row counts, errors) lives in PostgreSQL `pipeline_runs`. This keeps the ClickHouse schema clean.

## Query path

```
Browser → nginx (:5190)
       → proxy_pass → FastAPI (:8090)
       → ClickHouse query: SELECT date, value FROM records FINAL WHERE ...
       → JSON response → React chart component
```

Typical latency: < 50ms for 5-year monthly series (~60 rows). ClickHouse is extremely fast for this scale.
