# Sardonyx: built with Node and pnpm, served by nginx with /api/ passed on to
# the Lithica server and /data/ (the uploads) read from the data volume.

# The app is the same files on every platform, so it is built once, on the
# machine that builds the image.
FROM --platform=$BUILDPLATFORM node:26-trixie-slim AS build
ARG BUILDARCH

# pnpm at the version package.json names, as the single binary pnpm
# publishes, checked against its published SHA-256. (Node 26 has no
# corepack, and the project's packages are installed with pnpm only.)
ARG PNPM_VERSION=12.15.0
ARG PNPM_SHA256_AMD64=55b5ed0092bd11176c1669598e231ae52e7cedac59de6efd0d415730f37d0598
ARG PNPM_SHA256_ARM64=d7ce93a2c7d847d3a34bd3f559b60c14f578b1320c17cc352a2c5c5fdf956117
RUN set -eu; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    rm -rf /var/lib/apt/lists/*; \
    case "$BUILDARCH" in \
      amd64) arch=x64; sum=$PNPM_SHA256_AMD64 ;; \
      arm64) arch=arm64; sum=$PNPM_SHA256_ARM64 ;; \
      *) echo "no pnpm binary for $BUILDARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/pnpm.tar.gz \
      "https://github.com/pnpm/pnpm/releases/download/v${PNPM_VERSION}/pnpm-linux-${arch}.tar.gz"; \
    echo "$sum  /tmp/pnpm.tar.gz" | sha256sum -c -; \
    mkdir /opt/pnpm; \
    tar -xzf /tmp/pnpm.tar.gz -C /opt/pnpm; \
    rm /tmp/pnpm.tar.gz; \
    ln -s /opt/pnpm/pnpm /usr/local/bin/pnpm

WORKDIR /app
# the dependencies first: they change less often than the code
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build


FROM nginx:1.30-alpine AS release

# the server's container, as Docker Compose names it
ENV BACKEND_HOST=server
# nginx resolves BACKEND_HOST anew while it runs, so that the server can be
# restarted without the client; this is Docker's name server
ENV RESOLVER=127.0.0.11
# the secret of signed file links, the server's file_link_secret (README,
# "Signed file links"); empty: file links are not checked. Defined either
# way, so that the template always has it to fill in.
ENV FILE_LINK_SECRET=

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=755 docker-entrypoint.d/15-file-link-secret.sh /docker-entrypoint.d/
COPY --from=build /app/dist /usr/share/nginx/html

ARG BUILD_INFO=
ARG BUILD_DATE=
ARG SOURCE_COMMIT=
ARG DOCKER_REPO=
LABEL org.opencontainers.image.title="Sardonyx" \
      org.opencontainers.image.description="The web client for Lithica with the cards module" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/DominykasVad/lithica" \
      org.opencontainers.image.version="${BUILD_INFO}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${SOURCE_COMMIT}"
