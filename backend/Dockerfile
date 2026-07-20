# Backend Dockerfile for Render / Railway / Fly.io
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

# Copy dependency manifest first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Ensure Chromium browser binaries are available in the image
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python -m playwright install --with-deps chromium || true

ENV PYTHONUNBUFFERED=1

# Render injects the PORT env var; use it at runtime instead of a fixed port.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
