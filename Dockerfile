# syntax=docker/dockerfile:1.7

# ---- Stage 1: builder ----------------------------------------------------
# Resolves and installs runtime dependencies into an isolated virtualenv
# at ${VENV_PATH}. Poetry itself lives in a separate venv at ${POETRY_HOME}
# so it never ends up in the runtime image.
FROM python:3.12-slim-bookworm AS builder

ARG POETRY_VERSION=2.4.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_HOME=/opt/poetry \
    VENV_PATH=/opt/venv \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/poetry/bin:/opt/venv/bin:${PATH}"

# Build-time system packages required to compile any wheel that lacks a
# manylinux distribution (PyNaCl needs libffi headers on some platforms).
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        libffi-dev \
        libsodium-dev \
    && rm -rf /var/lib/apt/lists/*

# Poetry in its own venv -> not copied into runtime.
RUN python -m venv "${POETRY_HOME}" \
    && "${POETRY_HOME}/bin/pip" install --upgrade pip \
    && "${POETRY_HOME}/bin/pip" install "poetry==${POETRY_VERSION}"

# Target venv that will be copied into the runtime stage.
RUN python -m venv "${VENV_PATH}" \
    && "${VENV_PATH}/bin/pip" install --upgrade pip

WORKDIR /app

# Copy only the manifest layer first so dependency resolution is cached
# independently of source changes. A committed poetry.lock is required
# for reproducible builds; the build fails fast if it is absent.
COPY pyproject.toml poetry.lock ./

# Install only runtime dependencies into ${VENV_PATH}. POETRY_VIRTUALENVS_CREATE=false
# plus the leading entry in PATH ensures pip writes to /opt/venv.
RUN poetry install --only main --no-root


# ---- Stage 2: runtime ----------------------------------------------------
# Minimal image with ffmpeg + libopus for Discord voice. No build tools,
# no Poetry, no pip caches.
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VENV_PATH=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

# ffmpeg          -> required by yt-dlp for audio extraction / transcoding
# libopus0        -> required by PyNaCl/discord.py voice
# ca-certificates -> outbound HTTPS to Discord and YouTube
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ffmpeg \
        libopus0 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin --uid 1000 appuser

COPY --from=builder ${VENV_PATH} ${VENV_PATH}

WORKDIR /app

# Copy application source. .dockerignore keeps secrets and caches out.
COPY --chown=appuser:appuser bot.py config.py ./
COPY --chown=appuser:appuser cogs ./cogs
COPY --chown=appuser:appuser music ./music

USER appuser

# No port to EXPOSE: the bot maintains outbound websocket and voice
# connections only.

CMD ["python", "bot.py"]
