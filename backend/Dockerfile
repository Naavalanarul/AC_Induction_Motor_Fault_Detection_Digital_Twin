# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

FROM base AS deps
# Hash-pinned runtime dependencies (regenerate with pip-compile, see README).
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install --require-hashes -r requirements.txt
# PyTorch is optional (INSTALL_ML=false -> the vibration channel uses the rule-based fallback).
ARG INSTALL_ML=true
# Pin TORCH_VERSION for reproducible images once you have validated a version (empty = latest CPU build).
ARG TORCH_VERSION=
RUN --mount=type=cache,target=/root/.cache/pip if [ "$INSTALL_ML" = "true" ]; then \
      pip install "torch${TORCH_VERSION:+==$TORCH_VERSION}" --index-url https://download.pytorch.org/whl/cpu; fi

FROM deps AS runtime
ARG UID=10001
RUN adduser --disabled-password --gecos "" --home /nonexistent --shell /sbin/nologin --no-create-home --uid "${UID}" appuser
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
# --timeout-graceful-shutdown lets the lifespan stop workers and flush DB writes on SIGTERM
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--timeout-graceful-shutdown", "20"]
