#!/bin/sh
# Before the configuration is filled in: the secret of signed file links goes
# into it as it is, so it may have only the characters the server accepts.
set -eu
if [ -n "${FILE_LINK_SECRET:-}" ] && \
    ! printf '%s' "$FILE_LINK_SECRET" | grep -Eq '^[A-Za-z0-9_-]{32,}$'; then
  echo "FILE_LINK_SECRET must be at least 32 letters, digits, - or _" >&2
  exit 1
fi
