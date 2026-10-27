#!/usr/bin/dumb-init /bin/sh

# The secret of signed file links goes into the configuration as it is:
# only the characters the server accepts for it
if [ -n "${FILE_LINK_SECRET}" ] && \
    ! printf '%s' "${FILE_LINK_SECRET}" | grep -Eq '^[A-Za-z0-9_-]{32,}$'; then
  echo "FILE_LINK_SECRET must be at least 32 letters, digits, - or _" >&2
  exit 1
fi

# Integrate environment variables
sed -i "s|__BACKEND__|${BACKEND_HOST}|" \
  /etc/nginx/nginx.conf
sed -i "s|__FILE_LINK_SECRET__|${FILE_LINK_SECRET}|g" \
  /etc/nginx/nginx.conf
sed -i "s|__BASEURL__|${BASE_URL:-/}|g" \
  /var/www/index.htm \
  /var/www/manifest.json

# Start server
exec nginx
