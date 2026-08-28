FROM python:3.12-slim

# Install dependencies
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Create app user
RUN groupadd -r dashy && useradd -r -g dashy -d /app -s /sbin/nologin dashy

# App directory
RUN mkdir -p /app/config
WORKDIR /app

# Copy application
COPY main.py /app/main.py

# Ensure config directory exists
RUN chown -R dashy:dashy /app && chmod 755 /app

USER dashy

# Health check
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8081/healthz')" || exit 1

# Expose health check port
EXPOSE 8081

# Default config path
ENV DASHY_CONF=/app/config/conf.yml
ENV SYNC_INTERVAL=60

# Run the sidecar
CMD ["python3", "/app/main.py", "--conf", "${DASHY_CONF}"]

