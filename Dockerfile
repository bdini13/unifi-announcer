# syntax=docker/dockerfile:1
# UniFi Announcer — TTS + preset tones for UniFi Protect Smart Chimes
FROM python:3.12-slim

ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}
LABEL org.opencontainers.image.title="UniFi Announcer" \
      org.opencontainers.image.source="https://github.com/bdini13/unifi-announcer" \
      org.opencontainers.image.revision="${GIT_SHA}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the package, not only main.py: command adapters, dispatcher, cache,
# protocol boundaries, observability, and optional MCP composition are runtime dependencies.
COPY app /app/app

RUN useradd -m -u 1000 announcer && mkdir -p /data && chown announcer:announcer /data
USER announcer

EXPOSE 8095
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8095", "--workers", "1"]
