#!/usr/bin/env bash
# The stack the browser tests run against: the dev stack's server, Sardonyx
# and PostgreSQL, with docker-compose.e2e.yml on top (a mail catcher, a
# second site in nsfw-login, the cards to import). Its own project name: a
# dev stack beside it is left alone.
#
#   e2e/stack.sh up        build, start, wait until the sites answer
#   e2e/stack.sh down      stop it and drop its data
#   e2e/stack.sh logs      the logs of its containers
#   e2e/stack.sh compose … any docker compose command on it
#
# (from clients/sardonyx). The tests find it on the ports below.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
stack="$here/.stack"

export E2E_PORT=${E2E_PORT:-8092}
export E2E_NSFW_PORT=${E2E_NSFW_PORT:-8093}
export E2E_MAIL_PORT=${E2E_MAIL_PORT:-8095}
# Sardonyx's port in docker-compose.dev.yml; the legacy client is not started
export SARDONYX_PORT=$E2E_PORT
export PORT=${PORT:-8094}

compose() {
  docker compose -p lithica-e2e --project-directory "$root" \
    -f "$root/docker-compose.dev.yml" -f "$root/docker-compose.e2e.yml" "$@"
}

# The secrets of this stack: made for it, kept beside its configuration so
# that a second `up` (or `compose`) uses the same ones.
secrets() {
  mkdir -p "$stack"
  if [ ! -f "$stack/secrets" ]; then
    printf 'secret=%s\nfile_link_secret=%s\n' \
      "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" > "$stack/secrets"
  fi
  secret=$(sed -n 's/^secret=//p' "$stack/secrets")
  E2E_FILE_LINK_SECRET=$(sed -n 's/^file_link_secret=//p' "$stack/secrets")
  export E2E_FILE_LINK_SECRET
}

configs() {
  # The site the tests use: mail goes to the catcher, and the reset link
  # points at Sardonyx on its port.
  cat > "$stack/config.yaml" <<YAML
name: Lithica e2e
domain: http://localhost:$E2E_PORT
secret: $secret
data_dir: /data/
data_url: data/
smtp:
  host: mailpit
  port: 1025
  user: e2e
  pass: e2e
  from: lithica-e2e@example.com
YAML
  # The same site, as one in nsfw-login. Its own name, to tell them apart.
  sed -e "s/^name: .*/name: Lithica e2e (nsfw-login)/" "$stack/config.yaml" \
    > "$stack/config-nsfw.yaml"
  printf 'visibility: nsfw-login\n' >> "$stack/config-nsfw.yaml"
}

wait_for() {
  for _ in $(seq 1 180); do
    if curl -sf -o /dev/null -H 'Accept: application/json' "$1/api/info"; then
      return 0
    fi
    sleep 1
  done
  echo "$1 did not answer" >&2
  compose logs --tail 80 >&2
  return 1
}

case "${1:-}" in
  up)
    secrets
    configs
    compose up -d --build --wait --wait-timeout 300 server server-nsfw sardonyx sardonyx-nsfw sql mailpit
    wait_for "http://localhost:$E2E_PORT"
    wait_for "http://localhost:$E2E_NSFW_PORT"
    curl -sf -o /dev/null "http://localhost:$E2E_MAIL_PORT/api/v1/info"
    echo "e2e stack: http://localhost:$E2E_PORT (nsfw-login: $E2E_NSFW_PORT, mail: $E2E_MAIL_PORT)"
    ;;
  down)
    secrets
    compose down -v --remove-orphans
    rm -rf "$stack"
    ;;
  logs)
    secrets
    compose logs "${@:2}"
    ;;
  compose)
    secrets
    compose "${@:2}"
    ;;
  *)
    sed -n '2,13p' "$0"
    exit 2
    ;;
esac
