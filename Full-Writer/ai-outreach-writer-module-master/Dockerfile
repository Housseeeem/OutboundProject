FROM python:3.11-slim

WORKDIR /app

# Install deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

EXPOSE 8003

CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8003}"
