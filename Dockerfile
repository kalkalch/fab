# Optimized Dockerfile for FAB - Firewall Access Bot
FROM python:3.12-slim

# Create non-root user
RUN groupadd -r fab && useradd -r -g fab fab

# Set working directory
WORKDIR /app

# Ensure Python output is unbuffered
ENV PYTHONUNBUFFERED=1

# Install system dependencies (only what's needed)
RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories and set permissions
RUN mkdir -p data temp sessions && \
    chown -R fab:fab /app

# Switch to non-root user
USER fab

# Expose port
EXPOSE 8080

# Default command with unbuffered output
CMD ["python", "-u", "main.py"]
