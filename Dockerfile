# Dockerfile
# Base image includes Chromium + Playwright Python bindings + system deps
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

WORKDIR /app

# Keep pip tooling current (avoids many build issues)
RUN python -m pip install --upgrade pip setuptools wheel

# ---- Python deps (lean) ----
# IMPORTANT: Do NOT include "playwright" in requirements.txt when using this base image.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- App source ----
COPY . .

# Cloud Run/containers provide $PORT at runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

# Start FastAPI (shell form so $PORT expands)
CMD sh -c "python -m uvicorn server.app:app --host 0.0.0.0 --port ${PORT} --log-level debug"


