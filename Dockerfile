# syntax=docker/dockerfile:1

# Alpine-based: our app is pure Python stdlib, no native deps, no pip install.
# ~55MB base + ~1MB app = smallest viable image.
FROM python:3.13-alpine

LABEL org.opencontainers.image.title="yealink-fritzbox-phonebook-sync"
LABEL org.opencontainers.image.description="Fritzbox → Yealink phonebook sync server"
LABEL org.opencontainers.image.source="https://github.com/local/yealink-fritzbox-phonebook-sync"

# tini: minimal init for proper PID 1 signal forwarding (SIGTERM on docker stop)
RUN apk add --no-cache tini \
    && addgroup -S app \
    && adduser -S -G app -h /app app

WORKDIR /app

# Copy only the application file — nothing else needed
COPY --chown=app:app yealink-fritzbox-phonebook-sync.py .

# Python container best practices
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SYNC_LISTEN_PORT=8080

USER app

EXPOSE 8080

# Health check using wget (available in Alpine base)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O- "http://127.0.0.1:${SYNC_LISTEN_PORT}/health" || exit 1

# tini as PID 1, app as child — proper signal forwarding
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["python3", "/app/yealink-fritzbox-phonebook-sync.py"]
