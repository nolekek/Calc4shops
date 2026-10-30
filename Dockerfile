# Production Dockerfile for Deal Auditor
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build tools if necessary
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# --- Final Runtime Stage ---
FROM python:3.12-slim AS runner

WORKDIR /app

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy installed dependencies from builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

# Copy application source
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser .env.example .env

# Data directory for SQLite database
RUN mkdir -p /app/data && chmod -R 777 /app/data
ENV DATABASE_URL="sqlite+aiosqlite:////app/data/deals.db"

USER root

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/presets').read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
