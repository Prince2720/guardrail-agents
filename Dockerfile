FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    APP_ENV=production TRUST_PROXY=true AUDIT_DB=/tmp/audit.db

WORKDIR /app
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY app ./app
COPY data ./data

# run as a normal user, not root
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 7860
# Render sets $PORT; Hugging Face Spaces uses 7860
CMD ["sh", "-c", "uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
