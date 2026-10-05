# ---- News Provider API ----
# Build:  docker build -t news-provider .
# Run:    docker run -p 5000:5000 news-provider
# Then:   http://localhost:5000/news

FROM python:3.12-slim

# Keep Python lean and predictable inside the container
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000

WORKDIR /app

# System CA certificates so HTTPS scraping works out of the box
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first so Docker can cache this layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY . .

# Run as a non-root user
RUN useradd --create-home appuser
USER appuser

EXPOSE 5000

# Serve the Flask app with waitress (a real WSGI server, not the dev server)
CMD ["sh", "-c", "waitress-serve --listen=*:${PORT} main:app"]
