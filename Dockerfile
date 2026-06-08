# =============================================================================
# Dockerfile — multi-stage build for the india-findata Python API + scheduler
# =============================================================================
#
# Stage 1 (builder): install Python deps with uv into a virtual environment
# Stage 2 (runtime): copy only the venv + source, no build tools
#
# The web frontend is built and served separately (see web/Dockerfile).
# In Docker Compose, the `api` container runs this image.

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install uv — the package manager used by this project (much faster than pip)
RUN pip install --no-cache-dir uv

# Copy dependency manifests first (layer cache: rebuilds deps only when these change)
COPY pyproject.toml .

# Install all production dependencies into a venv at /build/.venv
# --no-dev skips pytest/ruff/mypy which aren't needed in the container
RUN uv venv .venv && \
    uv pip install --python .venv/bin/python -r <(uv pip compile pyproject.toml --no-dev) || \
    uv pip install --python .venv/bin/python .

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /build/.venv /app/.venv

# Copy application source
COPY pipeline/ ./pipeline/
COPY api/      ./api/
COPY scripts/  ./scripts/

# Use the venv's Python for all subsequent commands
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1

# Non-root user for security (principle of least privilege)
RUN useradd --create-home --no-log-init appuser
USER appuser

EXPOSE 8090

# Health check — polls the /health endpoint every 30s
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8090/health')"

# Start FastAPI with uvicorn.  --workers 1 because APScheduler runs in the same
# process and multiple workers would start duplicate schedulers.
CMD ["uvicorn", "pipeline.main:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1"]
