# syntax=docker/dockerfile:1.7

# =============================================================================
# Stage 1: build
# Installs Poetry and project dependencies into an in-project venv.
# BuildKit cache mounts keep poetry's package cache warm across builds.
# =============================================================================
FROM python:3.12-slim AS build

ENV POETRY_VERSION=2.3.3 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PYSETUP_PATH="/opt/pysetup" \
    VENV_PATH="/opt/pysetup/.venv"

ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --root-user-action=ignore "poetry==$POETRY_VERSION"

WORKDIR $PYSETUP_PATH

# Dependencies layer: invalidated only when pyproject.toml / poetry.lock change,
# NOT when src/ changes. This is what makes iterative builds fast.
COPY pyproject.toml poetry.lock ./
RUN --mount=type=cache,target=/root/.cache/pypoetry \
    poetry install --no-root --only main

# =============================================================================
# Stage 2: runtime
# Clean slim image with just the venv + app code. No Poetry, no pip cache, no
# build toolchain. The claude CLI shipped inside claude-agent-sdk is preserved
# because it lives in site-packages/ inside the copied venv.
# =============================================================================
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VENV_PATH="/opt/pysetup/.venv" \
    PATH="/opt/pysetup/.venv/bin:$PATH"

# Non-root user (claude CLI refuses --dangerously-skip-permissions as root).
# Home dir must be writable so the claude auth/credentials file can be mounted.
# No explicit UID: matches the default that previous images used, so existing
# claude-auth volumes (owned by the pre-existing UID) remain readable.
RUN useradd -m -s /bin/bash appuser && \
    mkdir -p /app /workspace && \
    chown -R appuser:appuser /app /workspace

# Copy the venv from the build stage (deps only, no source).
COPY --from=build --chown=appuser:appuser $VENV_PATH $VENV_PATH

# Copy app source last: edits to src/ only invalidate this single layer.
WORKDIR /app
COPY --chown=appuser:appuser . /app

USER appuser
EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
