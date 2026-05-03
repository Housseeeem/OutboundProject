# Detective Module - B2B Lead Generation Pipeline
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p ranking logs output

# Environment variables (to be set at runtime)
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Expose port for FastAPI server
EXPOSE 8002

# Default: run the FastAPI server (A2A + Redis subscriber)
# To run the old CLI pipeline instead: docker run ... python main.py
CMD sh -c "uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8002}"
