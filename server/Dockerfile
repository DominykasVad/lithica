# syntax=docker/dockerfile:1

ARG UV_VERSION=0.13.0

FROM astral/uv:${UV_VERSION} AS uv


# Runtime base: Python, system tools, the unprivileged user. No uv in here.
FROM python:3.13-slim-trixie AS base

# ffmpeg and ffprobe are called for video posts. libheif and libavif are not
# installed: the pillow-heif and pillow-avif-plugin wheels bundle them.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        dumb-init \
        ffmpeg \
 && rm -rf /var/lib/apt/lists/*

ARG PUID=1000
ARG PGID=1000
RUN groupadd --gid ${PGID} app \
 && useradd --uid ${PUID} --gid app --home-dir /opt/app --no-create-home app \
 && mkdir -p /opt/app /data \
 && chown app:app /opt/app /data

# The virtual environment lives outside /opt/app so that mounting the source
# over /opt/app in development does not hide it.
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/opt/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /opt/app


# Build stages: resolve nothing, install exactly what uv.lock says.
FROM base AS deps
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./


FROM deps AS deps-release
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project


FROM deps AS deps-dev
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project


FROM base AS testing
COPY --from=deps-dev /opt/venv /opt/venv
COPY --chown=app:app ./ /opt/app/

ENV TEST_ENVIRONMENT="true"
USER app
ENTRYPOINT ["pytest", "--tb=short"]
CMD ["lithica/"]


FROM base AS development
COPY --from=deps-dev /opt/venv /opt/venv
COPY --chown=app:app ./ /opt/app/

# the API documentation (docs, redoc, openapi.json) is on in development
ENV API_DOCS=1

USER app
CMD ["/opt/app/docker-start-dev.sh"]

ARG PORT=6666
ENV PORT=${PORT}
EXPOSE ${PORT}

ARG THREADS=4
ENV THREADS=${THREADS}

VOLUME ["/data/"]


FROM base AS release
COPY --from=deps-release /opt/venv /opt/venv
COPY --chown=app:app ./ /opt/app/
RUN rm -rf /opt/app/lithica/tests

USER app
CMD ["/opt/app/docker-start.sh"]

ARG PORT=6666
ENV PORT=${PORT}
EXPOSE ${PORT}

ARG THREADS=4
ENV THREADS=${THREADS}

ARG WORKERS=1
ENV WORKERS=${WORKERS}

VOLUME ["/data/"]

ARG DOCKER_REPO
ARG BUILD_DATE
ARG SOURCE_COMMIT
LABEL \
    maintainer="" \
    org.opencontainers.image.title="${DOCKER_REPO}" \
    org.opencontainers.image.url="https://github.com/DominykasVad/lithica" \
    org.opencontainers.image.documentation="https://github.com/DominykasVad/lithica/blob/${SOURCE_COMMIT}/doc/INSTALL.md" \
    org.opencontainers.image.created="${BUILD_DATE}" \
    org.opencontainers.image.source="https://github.com/DominykasVad/lithica" \
    org.opencontainers.image.revision="${SOURCE_COMMIT}" \
    org.opencontainers.image.licenses="GPL-3.0"
