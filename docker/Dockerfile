# Stage 1: build wheel
FROM python:3.11-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git ca-certificates \
  && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml pyproject.toml
COPY fixparser/ fixparser/
RUN python -m pip install --upgrade pip build
RUN python -m build -w -o /dist

# Stage 2: runtime image
FROM python:3.11-slim
LABEL org.opencontainers.image.source="https://github.com/Terrenus/fixtranslator"
WORKDIR /app
# create non-root user
RUN useradd --create-home appuser && mkdir /app/data && chown appuser:appuser /app/data
COPY --from=builder /dist/*.whl /tmp/package.whl
RUN python -m pip install --upgrade pip && python -m pip install /tmp/package.whl
USER appuser
ENV PORT=9000 PYTHONUNBUFFERED=1
EXPOSE 9000
# healthcheck (optional)
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:${PORT}/ || exit 1
CMD ["uvicorn", "fixparser.main:app", "--host", "0.0.0.0", "--port", "9000"]
