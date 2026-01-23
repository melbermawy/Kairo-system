# Kairo Backend Dockerfile
# Production-ready for Railway deployment

FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files first (needed for pip install)
COPY . .

# Install Python dependencies (not editable mode for production)
RUN pip install --no-cache-dir .

# Make startup script executable
RUN chmod +x scripts/start_production.sh

# Expose port (Railway sets $PORT)
EXPOSE 8000

# Start with our production script (runs worker + gunicorn)
CMD ["./scripts/start_production.sh"]
