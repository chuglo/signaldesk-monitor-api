FROM python:3.11.15-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 HOME=/tmp PATH=/app/.venv/bin:$PATH
WORKDIR /app
# Build from this repository: docker build --build-context service-kit=../signaldesk-service-kit .
COPY --from=service-kit pyproject.toml README.md /build/signaldesk-service-kit/
COPY --from=service-kit src /build/signaldesk-service-kit/src
COPY pyproject.toml README.md uv.lock /build/signaldesk-monitor-api/
COPY src /build/signaldesk-monitor-api/src
RUN python -m pip install uv==0.11.31 \
    && cd /build/signaldesk-monitor-api \
    && UV_PROJECT_ENVIRONMENT=/app/.venv uv sync --locked --no-dev --no-editable \
    && rm -rf /build
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
RUN chmod -R a=rX /app/alembic /app/alembic.ini
USER 10001:10001
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "signaldesk_monitor_api.main:create_configured_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-server-header", "--no-proxy-headers"]
