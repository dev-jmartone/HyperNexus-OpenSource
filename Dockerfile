# ==============================================================================
# Multi-stage Dockerfile for HyperNexus
# ==============================================================================

# ── Stage 1: Build Frontend SPA ──────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY web/frontend/package*.json ./
RUN npm ci

COPY web/frontend ./
RUN npm run build

# ── Stage 2: Production Python Runtime ──────────────────────────────────────
FROM python:3.12-slim AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000 \
    HOST=0.0.0.0

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code and seed scripts
COPY . .

# Copy compiled frontend assets from Stage 1
COPY --from=frontend-builder /app/frontend/dist ./web/frontend/dist

# Ensure data directory exists
RUN mkdir -p /app/data

EXPOSE 5000

# Healthcheck endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

# Start production Waitress server
CMD ["python", "server_prod.py"]
