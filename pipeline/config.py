"""
pipeline.config — application configuration loaded from environment variables.

Uses pydantic-settings to read values from:
  1. Environment variables (production / Docker)
  2. A .env file in the project root (local development)

All config is accessed through the module-level `settings` singleton.
Never hardcode credentials — always use these settings objects.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All runtime configuration for the pipeline + API.

    Attributes:
        clickhouse_host:    ClickHouse server hostname
        clickhouse_port:    ClickHouse HTTP port (default 8123)
        clickhouse_db:      Database name
        clickhouse_user:    ClickHouse user (default "default")
        clickhouse_password: ClickHouse password (empty = no auth)
        postgres_dsn:       Full PostgreSQL connection string
        mospi_api_token:    MOSPI esankhyiki API token (optional — skips MOSPI if unset)
        data_gov_in_api_key: data.gov.in API key (required for RBI rates + GDP)
        log_level:          Logging verbosity: DEBUG | INFO | WARNING | ERROR
        tz:                 Timezone for APScheduler (default Asia/Kolkata)
        api_port:           FastAPI listen port (default 8090)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_db: str = "indiafindata"
    clickhouse_user: str = "default"
    clickhouse_password: str = ""

    postgres_dsn: str = "postgresql://findata:findata_dev@localhost:5433/indiafindata"

    mospi_api_token: str = ""
    data_gov_in_api_key: str = ""

    log_level: str = "INFO"
    tz: str = "Asia/Kolkata"
    api_port: int = 8090


settings = Settings()
