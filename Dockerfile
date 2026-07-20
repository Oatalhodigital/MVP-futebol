# Backend Dockerfile for Render / Railway / Fly.io
# Render may be configured to use the repo root as build context.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

# The Playwright base image already ships Chromium binaries under /ms-playwright.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Copy dependency manifest first to leverage Docker cache
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY backend/ .

# Make the startup script executable
RUN chmod +x start.sh

ENV PYTHONUNBUFFERED=1

# Render injects the PORT env var; start.sh reads it and starts uvicorn.
CMD ["./start.sh"]
