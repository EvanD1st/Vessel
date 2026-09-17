#!/usr/bin/env bash
# One-time VESSEL-only host preparation. Does not edit AttendX files or services.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run as root'; exit 1; }
[[ $(uname -m) == x86_64 ]] || { echo 'Only Ubuntu x86_64 is supported'; exit 1; }
if ! id vessel-dashboard >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/vessel-dashboard --shell /usr/sbin/nologin vessel-dashboard
fi
install -d -o vessel-dashboard -g vessel-dashboard -m 0700 /var/lib/vessel-dashboard
install -d -o vessel-dashboard -g vessel-dashboard -m 0700 /var/lib/vessel-dashboard/owner-login
install -d -o root -g root -m 0755 /opt/vessel-dashboard /opt/vessel-dashboard/releases
install -d -o root -g root -m 0755 /opt/vessel-dashboard/runtime
if [[ ! -e /var/lib/vessel-dashboard/account.sqlite3 ]]; then
  install -o vessel-dashboard -g vessel-dashboard -m 0600 /dev/null /var/lib/vessel-dashboard/account.sqlite3
fi

version=v24.15.0
archive=node-${version}-linux-x64.tar.xz
target=/opt/vessel-dashboard/runtime/node-${version}-linux-x64
if [[ ! -x "$target/bin/node" ]]; then
  work=$(mktemp -d)
  trap 'rm -rf "$work"' EXIT
  curl --fail --silent --show-error --location "https://nodejs.org/dist/${version}/${archive}" -o "$work/$archive"
  curl --fail --silent --show-error --location "https://nodejs.org/dist/${version}/SHASUMS256.txt" -o "$work/SHASUMS256.txt"
  (cd "$work" && grep "  ${archive}$" SHASUMS256.txt | sha256sum --check --status)
  tar -xJf "$work/$archive" -C /opt/vessel-dashboard/runtime
  chown -R root:root "$target"
fi
ln -sfn "$target" /opt/vessel-dashboard/node

if [[ ! -e /etc/vessel-dashboard.env ]]; then
  umask 077
  secret=$(openssl rand -base64 48 | tr -d '\n')
  cat > /etc/vessel-dashboard.env <<EOF
VESSEL_TARGET=node
VESSEL_SQLITE_PATH=/var/lib/vessel-dashboard/account.sqlite3
VESSEL_AUTH_URL=https://vessel-cont.duckdns.org
VESSEL_AUTH_SECRET=${secret}
VESSEL_OWNER_FILE_DIR=/var/lib/vessel-dashboard/owner-login
HOST=127.0.0.1
PORT=8092
EOF
  chown root:vessel-dashboard /etc/vessel-dashboard.env
  chmod 0640 /etc/vessel-dashboard.env
fi
if [[ -e /etc/systemd/system/vessel-dashboard.service ]] && ! grep -q '^Description=VESSEL dashboard' /etc/systemd/system/vessel-dashboard.service; then
  echo 'Different vessel-dashboard.service exists; preserved' >&2; exit 1
fi
cat > /etc/systemd/system/vessel-dashboard.service <<'EOF'
[Unit]
Description=VESSEL dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=vessel-dashboard
Group=vessel-dashboard
WorkingDirectory=/opt/vessel-dashboard/current
EnvironmentFile=/etc/vessel-dashboard.env
ExecStart=/opt/vessel-dashboard/node/bin/node /opt/vessel-dashboard/current/server.js
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/vessel-dashboard
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
LimitNOFILE=4096

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
install -o root -g root -m 0755 "$(dirname "$0")/deploy.sh" /usr/local/sbin/vessel-deploy
echo 'VESSEL host prepared in separate directories. AttendX was not changed.'
