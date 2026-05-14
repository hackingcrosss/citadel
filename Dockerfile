FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    whois \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create non-root user
RUN useradd -m -u 1000 citadel && chown -R citadel:citadel /app
USER citadel

EXPOSE 5000

CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:create_app()"]