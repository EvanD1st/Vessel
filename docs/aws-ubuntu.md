# Ubuntu dashboard release

VESSEL's hosted dashboard runs as `vessel-dashboard.service` under its own unprivileged user. Its Node runtime and releases live in `/opt/vessel-dashboard`; its private SQLite database and owner login file live in `/var/lib/vessel-dashboard`. The service listens only on `127.0.0.1:8092`. Caddy serves `https://vessel-cont.duckdns.org` and proxies this loopback port. The existing AttendX directories, service, and Caddy site stay separate.

The dashboard is an account and companion view. The Cline integration, provider key, native capture, checkpoint custody, and recovery operations still run on the owner's Windows computer. A hosted login by itself does not make the local companion reachable. Pair the installed VS Code extension to the hosted HTTPS origin and keep the local companion running for live data.

## Initial host preparation

The owner must point `vessel-cont.duckdns.org` to the Ubuntu public IP and ensure ports 80/443 are reachable. Run `sudo bash deploy/ubuntu/bootstrap.sh` once on the server from a trusted checkout that also contains `deploy/ubuntu/deploy.sh`. The bootstrap installs a verified Node 24.15.0 tarball, generates a private authentication secret in `/etc/vessel-dashboard.env`, creates a separate user and systemd unit, and installs `/usr/local/sbin/vessel-deploy`. It does not change Caddy or start VESSEL until a tested release is staged.

The release artifact is `vessel-dashboard-release.tar.gz`, built from `dashboard/dist/standalone` by CI after the Python, dashboard, browser, and extension checks. It contains `server.js`, its static assets and bundled dependencies, the tested VSIX at `public/downloads/vessel.vsix`, and `scripts/migrate-selfhost.py` plus `scripts/bootstrap-selfhost.mjs`. Stage it as `/home/ubuntu/vessel-staging/<40-character-git-sha>.tar.gz`; then run `sudo /usr/local/sbin/vessel-deploy <sha>`. The deployer checks paths, backs up SQLite, applies hash-checked migrations, switches the release symlink, checks loopback health and the VSIX download, and adds the separate Caddy site after validation. The prior application release is restored if the new service fails its health checks. Database backups remain private; a schema migration may require restoring its matching backup before downgrading.

Once deployed, create the first owner with the installed Node runtime and the server-private database:

```sh
sudo -u vessel-dashboard env VESSEL_SQLITE_PATH=/var/lib/vessel-dashboard/account.sqlite3 VESSEL_OWNER_FILE_DIR=/var/lib/vessel-dashboard/owner-login /opt/vessel-dashboard/node/bin/node /opt/vessel-dashboard/current/scripts/bootstrap-selfhost.mjs jamesevan393@gmail.com
```

The command prints only the path to a mode-0600 login file. Read the temporary password over your own SSH session with `sudo cat <printed-path>`, sign in at the HTTPS site, and change the password immediately. Do not paste the password or the login file into issues, chat, or the repository. Public registration and password reset are available; the owner can manage accounts from the dashboard.

## GitHub Actions deployment

The `Checks` workflow always builds and tests. A successful push to `main` deploys the dashboard and tested VSIX when repository secrets `VESSEL_DEPLOY_SSH_KEY` (a dedicated SSH deploy key with access as `ubuntu`) and `VESSEL_DEPLOY_KNOWN_HOSTS` (the verified server host key line, obtained and checked out of band). The `ubuntu` account needs passwordless sudo to install the reviewed deploy helper and run `/usr/local/sbin/vessel-deploy`, plus permission to stage files in its own `~/vessel-staging` directory. Never use the account owner password or companion key as a CI secret.

Check `systemctl status vessel-dashboard.service`, `journalctl -u vessel-dashboard.service`, `curl -I https://vessel-cont.duckdns.org/setup-guide`, and the AttendX HTTPS route after deployment. The DuckDNS record may need updating if the server's public IP changes. For a manual application rollback, identify the previous release under `/opt/vessel-dashboard/releases`, repoint `/opt/vessel-dashboard/current` as root, and restart only `vessel-dashboard.service`; restore its matching SQLite backup if the schema changed.
