#!/bin/sh
# Sardonyx is served at the root of its host: serving it under a path is
# not supported. A compose file carried over from an older release may
# still pass BASE_URL, and the site would then be where it was not meant to
# be, without a word. "/" and empty are the root.
set -eu
case "${BASE_URL:-/}" in
  /) ;;
  *)
    echo "WARNING: BASE_URL is set (${BASE_URL}) and ignored: serving the site" \
      "under a path is not supported; it is served at the root of its host." >&2
    ;;
esac
