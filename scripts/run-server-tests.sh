#!/usr/bin/env bash
# Usage: scripts/run-server-tests.sh [path]
# - path: optional dir/file/node (default: lithica/, example, lithica/tests/api/test_info.py)

set -euo pipefail

cd "$(dirname "$0")/.."

# Build the testing image (with xdist)
docker buildx build --load --target testing -t lithica-server-tests ./server

# Start the test database; the test container joins its network.
docker compose -f server/docker-compose.test.yml up -d --wait
TEST_DATABASE_URL="postgresql://postgres:postgres@db:5432/postgres"

# Optional path filter (dir/file/node), default to full suite.
TARGET="${1:-lithica/}"

run_tests() {
  local output_file
  output_file=$(mktemp)
  if docker run --rm -t \
      --network lithica-test_default \
      -e LITHICA_TEST_DATABASE_URL="$TEST_DATABASE_URL" \
      lithica-server-tests "$@" 2>&1 | tee "$output_file"; then
    rm -f "$output_file"
    return 0
  fi

  local status=${PIPESTATUS[0]}
  echo "docker run failed with exit code ${status}."
  echo "----- docker run output -----"
  cat "$output_file"
  echo "-----------------------------"
  if grep -qE "no tests ran|collected 0 items" "$output_file"; then
    echo "No tests collected for target '${TARGET}'."
    echo "Check the path (tests live under lithica/ in the container, so an example path looks like \`lithica/tests/api/test_info.py\`)."
  fi
  rm -f "$output_file"
  return "$status"
}

# Run in parallel.
run_tests -n auto --dist=loadfile --color=yes "$TARGET"
