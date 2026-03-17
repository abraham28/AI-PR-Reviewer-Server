# AI PR Reviewer – backend + frontend
FROM python:3.12-slim

WORKDIR /app

# Backend
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ /app/backend/

# Frontend (static)
COPY frontend/ /app/frontend/

# Persist settings (optional: use volume)
RUN mkdir -p /app/backend/data

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
# Use PORT from environment (e.g. Railway) or default 8000
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]

WORKDIR /app/backend
