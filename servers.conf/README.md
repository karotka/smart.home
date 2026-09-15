# Server / proxy infrastructure

Reverse-proxy + Cloudflare-tunnel layer that fronts the smart-home app.
The **application** (FastAPI in Docker `smart-home` :8001, Frigate :5000,
Mosquitto WS :8884, Grafana :3000) has always run on **192.168.0.224**
(`home`, Ubuntu 24.04). This directory captures the *proxy* layer.

## Entry paths

| Path | Name | How it reaches nginx | Auth |
|------|------|----------------------|------|
| Remote | `home.karotka.cz`, `panel.karotka.cz` | Cloudflare tunnel `f04eabe1…` → `cloudflared` → `localhost:80` | source is 127.0.0.1 → **basic-auth** |
| LAN | `pi.karotka.cz` | public A-record → host :443 (Let's Encrypt) | source is 192.168.0.0/16 → **skips** auth |

There is **no router port-forward** — the tunnel is an outbound connection.
The only "routing" is DNS, all held in Cloudflare:
`home`/`panel` are CNAMEs to the tunnel; `pi.karotka.cz` is an A-record
to a private LAN IP.

## Migration: Pi4 (.222) → home (.224)

Historically this proxy layer lived on the Pi4 at **192.168.0.222** (`cml`).
It has been mirrored onto **.224** so the Pi4 can be retired. On .224 the
proxy targets are `127.0.0.1` (backends are local) instead of `192.168.0.224`.

### Files (as deployed on .224)
- `default`            → `/etc/nginx/sites-available/default`  (port 80 tunnel entry + :443 self-signed)
- `pi.karotka.cz`      → `/etc/nginx/sites-available/pi.karotka.cz` (LAN HTTPS, Let's Encrypt)
- `cloudflared.config.yml` → `/etc/cloudflared/config.yml`
- `mosquitto.conf`     → mosquitto broker config (:1883 + :8884 WS)

### Secrets NOT in git (copied host-to-host during migration)
- `/etc/cloudflared/f04eabe1-….json`      — tunnel credentials (600 root)
- `/etc/nginx/htpasswd/smart_home`         — basic-auth (640 root:www-data)
- `/etc/ssl/pi.karotka.cz/{fullchain,key}.pem` — Let's Encrypt cert (expires 2026-11-15)
- `/etc/ssl/{certs/selfsigned.crt,private/selfsigned.key}` — regenerated on .224

### TLS renewal for pi.karotka.cz — **acme.sh** (lives on .222, must move)
The cert is auto-renewed by **acme.sh** on .222 (NOT certbot), using a
**Cloudflare DNS-01** challenge (`dns_cf`), EC-256 key. Cron `38 12 * * *`
runs `~/.acme.sh/acme.sh --cron`; next renew 2026-10-16 (expires 2026-11-15).
Deploy/reload hook (`Le_ReloadCmd`):
```
sudo chgrp www-data /etc/ssl/pi.karotka.cz/*.pem && \
sudo chmod 640 /etc/ssl/pi.karotka.cz/*.pem && sudo systemctl reload nginx
```
To move to .224: run **`acme.sh.setup.sh`** (in this dir) with `CF_Token` exported
(token lives in `~/.acme.sh/account.conf` on .222 as `SAVED_CF_Token`). It installs
acme.sh, issues the EC-256 cert via Cloudflare DNS-01 to `/etc/ssl/pi.karotka.cz/`,
and wires the reload hook. Until then .224's cert copy goes stale after each .222
renewal — re-copy or cut over.

### Also on .222, NOT part of the serving path (context for retirement)
- **Kiosk display (no longer needed)**: cron `cron.start.browser.sh` launches a
  firefox-esr kiosk via `etc/browser start`; plus `lightdm`, `rpi-display-backlight`.
  The Pi4 was the wall display, but access is now **mobile-only** — this role is
  simply dropped at retirement, nothing replaces it.
- No smart-home python/gunicorn daemons run on .222 — the app is entirely on .224.
  The `invertor/heatpump` log-truncation crons on .222 target stale logs nothing writes.
- Legacy/harmless: disabled ngrok dyn-DNS cron, exim4 local mail, `pi-websocket/`,
  `conn.sh`, old `hp.data`/`invertor.data` InfluxDB dumps.

### Cutover runbook
1. **[done]** Install nginx + cloudflared on .224, place configs + secrets, `nginx -t`, start both.
   `cloudflared` runs as a 2nd connector of the same tunnel → zero-downtime redundancy.
2. **Move TLS renewal** (acme.sh) to .224: run `acme.sh.setup.sh` (see section above).
3. **Retire remote entry on .222:** `sudo systemctl disable --now cloudflared` on .222.
   Cloudflare then serves the tunnel only via .224.
4. **Repoint LAN name:** in Cloudflare DNS change `pi.karotka.cz` A-record
   `192.168.0.222` → `192.168.0.224`. (Needs dashboard/API — not a tunnel route.)
5. **Retire .222 nginx:** `sudo systemctl disable --now nginx` on .222.
6. Kiosk role is dropped (access is mobile-only) — no action.
