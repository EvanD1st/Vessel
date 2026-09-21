#!/usr/bin/env bash
# Promote a tested Linux standalone artifact, retaining the previous release.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run as root'; exit 1; }
release=${1:-}
[[ "$release" =~ ^[a-f0-9]{40}$ ]] || { echo 'Release must be a Git commit SHA'; exit 1; }
archive=/home/ubuntu/vessel-staging/${release}.tar.gz
[[ -f "$archive" && ! -L "$archive" ]] || { echo 'Missing release archive'; exit 1; }
root=/opt/vessel-dashboard
target=$root/releases/$release
old=$(readlink -f "$root/current" 2>/dev/null || true)
activate_release() {
  local destination=$1
  local candidate=$root/.current-${release}
  rm -f "$candidate"
  ln -sT "$destination" "$candidate"
  mv -Tf "$candidate" "$root/current"
}
if [[ ! -d "$target" ]]; then
  mkdir -m 0755 "$target"
  # A release is built from the checked commit and is transferred over pinned SSH.
  archive_list=$(mktemp)
  trap 'rm -f "$archive_list"' EXIT
  tar -tzf "$archive" > "$archive_list"
  grep -Eq '^\./server.js$' "$archive_list"
  grep -Eq '^\./scripts/migrate-selfhost.py$' "$archive_list"
  grep -Eq '^\./scripts/bootstrap-selfhost.mjs$' "$archive_list"
  if grep -Eq '(^/|(^|/)\.\.(/|$))' "$archive_list"; then echo 'Unsafe archive path'; exit 1; fi
  tar -xzf "$archive" -C "$target" --no-same-owner
  [[ -f "$target/server.js" ]] || { echo 'Missing standalone server'; exit 1; }
  [[ -s "$target/public/downloads/vessel.vsix" ]] || { echo 'Missing extension download'; exit 1; }
  chown -R root:root "$target"
fi
database=/var/lib/vessel-dashboard/account.sqlite3
backup=/var/lib/vessel-dashboard/account-before-${release}.sqlite3
if [[ ! -e "$backup" ]]; then
  runuser -u vessel-dashboard -- python3 -c 'import sqlite3,sys; source=sqlite3.connect(sys.argv[1]); target=sqlite3.connect(sys.argv[2]); source.backup(target); target.close(); source.close()' "$database" "$backup"
  chmod 0600 "$backup"
fi
# Migrations are append-only, hash checked and transactional. Backups stay private.
runuser -u vessel-dashboard -- python3 "$target/scripts/migrate-selfhost.py" --database "$database"
activate_release "$target"
systemctl enable --now vessel-dashboard.service
systemctl restart vessel-dashboard.service
ready=0
for attempt in {1..40}; do
  # Account session endpoints intentionally reject direct loopback origins.
  # The public reverse proxy is validated after this private service check.
  if curl --fail --silent --output /dev/null http://127.0.0.1:8092/setup-guide &&
     curl --fail --silent --head --output /dev/null http://127.0.0.1:8092/downloads/vessel.vsix; then
    ready=1; break
  fi
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  if [[ -n "$old" && -d "$old" ]]; then
    activate_release "$old"; systemctl restart vessel-dashboard.service
  fi
  echo 'VESSEL failed health checks; previous application release restored. Database backup retained.' >&2
  exit 1
fi

if ! grep -q '^# VESSEL dashboard managed block$' /etc/caddy/Caddyfile; then
  backup_caddy=/etc/caddy/Caddyfile.before-vessel-$(date -u +%Y%m%dT%H%M%SZ)
  cp -p /etc/caddy/Caddyfile "$backup_caddy"
  cat >> /etc/caddy/Caddyfile <<'EOF'

# VESSEL dashboard managed block
vessel-cont.duckdns.org {
    encode gzip
    reverse_proxy 127.0.0.1:8092 {
        header_up CF-Connecting-IP {remote_host}
        header_up X-Forwarded-Proto https
        header_up X-Forwarded-Host vessel-cont.duckdns.org
    }
}
EOF
  if ! caddy validate --config /etc/caddy/Caddyfile; then
    cp -p "$backup_caddy" /etc/caddy/Caddyfile
    echo 'Caddy validation failed; original config restored' >&2
    exit 1
  fi
  systemctl reload caddy.service
fi
# Existing VESSEL Caddy installations serve downloads from a separate
# directory ahead of the application proxy. Keep that file in step with the
# VSIX tested and packaged in this release.
if grep -Fq 'handle /downloads/*' /etc/caddy/Caddyfile &&
   grep -Fq 'root * /var/www/vessel' /etc/caddy/Caddyfile; then
  install -d -o root -g root -m 0755 /var/www/vessel/downloads
  staged_download=/var/www/vessel/downloads/.vessel-${release}.vsix
  install -o root -g root -m 0644 "$target/public/downloads/vessel.vsix" "$staged_download"
  mv -f "$staged_download" /var/www/vessel/downloads/vessel.vsix
  cmp -s "$target/public/downloads/vessel.vsix" /var/www/vessel/downloads/vessel.vsix || {
    echo 'Public VSIX does not match the tested release' >&2; exit 1;
  }
fi
echo "VESSEL dashboard release $release healthy; AttendX configuration retained."
