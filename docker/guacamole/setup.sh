#!/usr/bin/env bash
# One-time (and re-runnable) Guacamole setup for the lab. Reads .env.
#   1. writes init/initdb.sql (PostgreSQL schema) if missing
#   2. starts the stack
#   3. sets the guacadmin password, creates/updates the Qure laptop connection,
#      creates GUAC_USERS (optional local logins; random password, printed once)
#   4. applies sso-group.sql: every account, incl. SSO users created at first
#      sign-in, joins "qure-laptop-users" with READ on the connection
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo "create .env from .env.example first" >&2; exit 1; }
set -a; . ./.env; set +a
API=http://localhost:8096/api   # direct to Guacamole, bypassing sso-gate
CONN_NAME="Qure laptop (MinXray / qTrack)"

mkdir -p init
[ -s init/initdb.sql ] || docker run --rm guacamole/guacamole:1.6.0 /opt/guacamole/bin/initdb.sh --postgresql > init/initdb.sql
chmod 755 init && chmod 644 init/initdb.sql   # read by the postgres container user

# Recordings: guacd (uid 1000) writes, the web app (group 1000) reads.
docker volume create guacamole_recordings >/dev/null
docker run --rm -v guacamole_recordings:/r alpine sh -c 'chown 1000:1000 /r && chmod 2750 /r'

docker compose up -d
echo -n "Waiting for Guacamole"
until curl -sf -o /dev/null $API/languages; do echo -n .; sleep 3; done; echo

token() { curl -sf -X POST $API/tokens --data-urlencode "username=$1" --data-urlencode "password=$2" | jq -r .authToken; }
T=$(token guacadmin "$GUAC_ADMIN_PASSWORD" || true)
if [ -z "$T" ] || [ "$T" = null ]; then
  T=$(token guacadmin guacadmin)
  curl -sf -X PUT "$API/session/data/postgresql/users/guacadmin/password?token=$T" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg n "$GUAC_ADMIN_PASSWORD" '{oldPassword:"guacadmin", newPassword:$n}')"
  echo "guacadmin password set"
fi
D="$API/session/data/postgresql"

conn=$(jq -nc --arg name "$CONN_NAME" --arg h "$QURE_RDP_HOST" --arg u "$QURE_RDP_USER" --arg p "$QURE_RDP_PASSWORD" '{
  parentIdentifier: "ROOT", name: $name, protocol: "rdp",
  parameters: {
    hostname: $h, port: "3389", username: $u, password: $p,
    security: "nla", "ignore-cert": "true",
    "resize-method": "display-update", "enable-font-smoothing": "true",
    "disable-copy": "true",
    "recording-path": "/recordings", "create-recording-path": "true",
    "recording-name": "${GUAC_DATE}-${GUAC_TIME}-${GUAC_USERNAME}-qure"
  },
  attributes: { "max-connections": "1", "max-connections-per-user": "1" }
}')
id=$(curl -sf "$D/connections?token=$T" | jq -r --arg n "$CONN_NAME" 'to_entries[] | select(.value.name==$n) | .key' | head -1)
if [ -n "$id" ]; then
  curl -sf -X PUT "$D/connections/$id?token=$T" -H 'Content-Type: application/json' -d "$conn"
  echo "connection updated (id $id)"
else
  id=$(curl -sf -X POST "$D/connections?token=$T" -H 'Content-Type: application/json' -d "$conn" | jq -r .identifier)
  echo "connection created (id $id)"
fi

for u in ${GUAC_USERS:-}; do
  if curl -sf -o /dev/null "$D/users/$u?token=$T"; then
    echo "user $u exists"
  else
    pw=$(head -c 64 /dev/urandom | tr -dc A-Za-z0-9 | head -c 16)
    curl -sf -X POST "$D/users?token=$T" -H 'Content-Type: application/json' \
      -d "$(jq -nc --arg u "$u" --arg p "$pw" '{username:$u, password:$p, attributes:{}}')" >/dev/null
    echo "user $u created, initial password: $pw   (shown once; change it after first sign-in)"
  fi
  curl -sf -X PATCH "$D/users/$u/permissions?token=$T" -H 'Content-Type: application/json' \
    -d "[{\"op\":\"add\",\"path\":\"/connectionPermissions/$id\",\"value\":\"READ\"}]"
done

curl -sf -X DELETE "$API/tokens/$T" >/dev/null || true

docker exec -i guacamole-db psql -q -v ON_ERROR_STOP=1 -U guacamole -d guacamole_db < sso-group.sql
echo "SSO group applied"
echo "Done. Users: https://qure.imladrislab.org/ (PIH sign-in). Admin: ssh -L 8096:localhost:8096, then http://localhost:8096/"
