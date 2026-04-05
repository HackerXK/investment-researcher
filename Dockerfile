FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install the package
RUN pip install --no-cache-dir .

# Create data directories
RUN mkdir -p /app/data/edgar /app/data/duckdb /app/data/state

# Default environment variables
ENV EDGAR_LOCAL_DATA_DIR=/app/data/edgar
ENV DUCKDB_PATH=/app/data/duckdb/financial_timeseries.duckdb
ENV STATE_DB_PATH=/app/data/state/ingestion_state.db

# Entry point
CMD ["python", "-m", "investment_researcher.service"]
