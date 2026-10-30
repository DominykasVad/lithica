#!/bin/sh
# Sardonyx is served at the root of its host: it has no base path. BASE_URL
# belongs to the legacy client image; a compose file carried over from
# before 0.3.0 may still pass it to this one, and the site would then be
# where it was not meant to be, without a word. "/" and empty are the root.
set -eu
case "${BASE_URL:-/}" in
  /) ;;
  *)
    echo "WARNING: BASE_URL is set (${BASE_URL}) and ignored: Sardonyx is served" \
      "at the root of its host. To serve the site under a path, run the legacy" \
      "client (docker compose --profile legacy, see doc/UPGRADING.md)." >&2
    ;;
esac
