# Two stage build: compile the frontend, then serve it from FastAPI so the
# whole app is one container on one port. Works on Hugging Face Spaces (docker
# sdk, port 7860) and on any container host (Render, Railway, Fly).

# Stage 1: build the React bundle
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: python runtime
FROM python:3.11-slim
# ffmpeg is required for probing and preprocessing; nothing else is needed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Hugging Face Spaces routes traffic to 7860. The app serves the API and the
# built frontend from this single port. HF caches (torch hub, huggingface) go
# to a writable dir so the container does not try to write to a read-only home.
ENV HF_HOME=/app/.cache/huggingface \
    TORCH_HOME=/app/.cache/torch \
    XDG_CACHE_HOME=/app/.cache
EXPOSE 10000

CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
