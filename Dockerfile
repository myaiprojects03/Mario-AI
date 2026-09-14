FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies via pre-compiled binary wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=1000 -r requirements.txt

# Copy codebase and production models
COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "-m", "core.live_publisher"]
