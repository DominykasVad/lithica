#!/usr/bin/env bash
# Build the image and check what its nginx serves, with no server behind it:
# the configuration is valid, the app and its assets come with the security
# headers, an uploaded file is served with its own policy, temporary uploads
# are not served at all, and a path of the app is answered with the app.
# Then, with FILE_LINK_SECRET set, that a post's file and thumbnail are
# served only to a signed link, and an avatar as before.
#
#   scripts/test-image.sh          (from clients/sardonyx)
set -euo pipefail

image=sardonyx-image-test
container=sardonyx-image-test
signed=sardonyx-image-test-signed
port=${PORT:-18080}
signed_port=$((port + 1))
data=$(mktemp -d)
trap 'docker rm -f "$container" "$signed" >/dev/null 2>&1 || true; rm -rf "$data"' EXIT

mkdir -p "$data/posts" "$data/temporary-uploads" "$data/generated-thumbnails" "$data/avatars"
printf 'a stored file' > "$data/posts/1_test.png"
printf 'a thumbnail' > "$data/generated-thumbnails/1_test.jpg"
printf 'an avatar' > "$data/avatars/someone.png"
printf 'an upload in waiting' > "$data/temporary-uploads/abc.dat"
chmod -R a+rX "$data"

docker build -q -t "$image" . > /dev/null
if docker run --rm "$image" nginx -t > /dev/null 2>&1; then
  echo "ok    the nginx configuration is valid"
else
  docker run --rm "$image" nginx -t
  exit 1
fi
docker run -d --name "$container" -p "127.0.0.1:$port:80" -v "$data:/data:ro" "$image" > /dev/null

base="http://127.0.0.1:$port"
for _ in $(seq 1 50); do
  curl -sf -o /dev/null "$base/" && break
  sleep 0.2
done

failed=0
check() {
  # check <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    echo "ok    $1"
  else
    echo "FAIL  $1: expected '$2', got '$3'"
    failed=1
  fi
}
# --path-as-is: send ".." and "//" as written, for nginx to deal with
status() { curl -s --path-as-is -o /dev/null -w '%{http_code}' "$base$1"; }
header() { curl -s -D - -o /dev/null "$base$1" | tr -d '\r' | grep -i "^$2:" | cut -d' ' -f2- || true; }

app_csp="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
asset=$(curl -s "$base/" | grep -o '/assets/[^"]*\.js' | head -n 1)

for path in / /some/page "$asset"; do
  check "$path is served" 200 "$(status "$path")"
  check "$path has the app's policy" "$app_csp" "$(header "$path" Content-Security-Policy)"
  check "$path has nosniff" nosniff "$(header "$path" X-Content-Type-Options)"
  check "$path has the referrer policy" same-origin "$(header "$path" Referrer-Policy)"
  check "$path may not be framed" DENY "$(header "$path" X-Frame-Options)"
done
check "a path of the app is the app" "$(curl -s "$base/")" "$(curl -s "$base/some/page")"

check "an uploaded file is served" "a stored file" "$(curl -s "$base/data/posts/1_test.png")"
check "an uploaded file has nosniff" nosniff "$(header /data/posts/1_test.png X-Content-Type-Options)"
check "an uploaded file may run nothing" "default-src 'none'; sandbox" \
  "$(header /data/posts/1_test.png Content-Security-Policy)"

for path in /data/temporary-uploads/abc.dat /data/temporary-uploads/ \
  /data//temporary-uploads/abc.dat /data/posts/../temporary-uploads/abc.dat \
  /data/%74emporary-uploads/abc.dat; do
  check "$path is not served" 404 "$(status "$path")"
done

# Signed file links: the formula of nginx's secure_link_md5, worked out here
# with openssl, as the server's file_links works it out in Python
secret=test-secret-of-signed-file-links-0123456789
sign() {
  # sign <path under /data> <expiry>
  printf '%s%s %s' "$2" "$1" "$secret" | openssl md5 -binary | openssl base64 |
    tr '+/' '-_' | tr -d '='
}
check "a short secret is refused at start" 1 \
  "$(docker run --rm -e FILE_LINK_SECRET=short "$image" nginx -t >/dev/null 2>&1; echo $?)"
docker run -d --name "$signed" -p "127.0.0.1:$signed_port:80" -v "$data:/data:ro" \
  -e FILE_LINK_SECRET="$secret" "$image" > /dev/null
base="http://127.0.0.1:$signed_port"
for _ in $(seq 1 50); do
  curl -sf -o /dev/null "$base/" && break
  sleep 0.2
done
later=$(($(date +%s) + 3600))
earlier=$(($(date +%s) - 3600))
for path in /posts/1_test.png /generated-thumbnails/1_test.jpg; do
  good="$path?e=$later&s=$(sign "$path" "$later")"
  check "$path with a valid signature is served" 200 "$(status "/data$good")"
  check "$path without a signature is refused" 403 "$(status "/data$path")"
  check "$path with a wrong signature is refused" 403 \
    "$(status "/data$path?e=$later&s=$(sign /posts/2_other.png "$later")")"
  check "$path with another expiry is refused" 403 \
    "$(status "/data$path?e=$((later + 1))&s=$(sign "$path" "$later")")"
  check "$path with an expired signature is refused" 403 \
    "$(status "/data$path?e=$earlier&s=$(sign "$path" "$earlier")")"
done
# another spelling of the same file is the same file to nginx: still checked
for path in /data//posts/1_test.png /data/%70osts/1_test.png /data/posts/./1_test.png \
  /data/avatars/../posts/1_test.png /data/./generated-thumbnails/1_test.jpg; do
  check "$path without a signature is refused" 403 "$(status "$path")"
done
check "a signed file still has its policy" "default-src 'none'; sandbox" \
  "$(header "/data/posts/1_test.png?e=$later&s=$(sign /posts/1_test.png "$later")" Content-Security-Policy)"
check "an avatar needs no signature" 200 "$(status /data/avatars/someone.png)"
check "temporary uploads are still not served" 404 \
  "$(status "/data/temporary-uploads/abc.dat?e=$later&s=$(sign /temporary-uploads/abc.dat "$later")")"

exit "$failed"
