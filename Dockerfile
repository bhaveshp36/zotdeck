# ==============================================================================
# ZotDeck - The Lightweight Web Dashboard for Zot OCI Registry
# ==============================================================================
FROM python:3.11-alpine

# Set environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    ZOT_ENDPOINT=http://zot-registry:5000 \
    ZOT_PUBLIC_DOMAIN=registry.example.com

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

# Create non-root user
RUN adduser -D -u 1000 zotdeck && \
    chown -R zotdeck:zotdeck /app

USER zotdeck

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
