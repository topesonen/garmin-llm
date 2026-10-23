# Server

The page runs on a small Hetzner server (`ubuntu-4gb-hel1-2`: Ubuntu 24.04, 2 vCPU, 4 GB RAM) and is reachable over HTTPS from Topias's Tailscale devices only. Set up on 2026-10-19 (M3).

## Layout

| What | Where | Owner, mode |
|---|---|---|
| Code, a clone of this repo over HTTPS | `/opt/garmin-llm` | `garmin` |
| Virtual environment | `/opt/garmin-llm/.venv` | `garmin` |
| Database, rebuilt hourly from the Garmin API | `/opt/garmin-llm/data/warehouse/garmin.duckdb` (folder `garmin-sync:garmin 750`) | `garmin-sync:garmin 640` |
| Place names stripped from titles | `/opt/garmin-llm/data/private/place_names.txt` (folder `700`) | `garmin-sync:garmin 600` |
| Garmin Personal API key (`GARMIN_API_KEY=...`) | `/etc/garmin-llm-sync.env` | `root:root 600` |
| API key (`ANTHROPIC_API_KEY=...`, its own key) | `/etc/garmin-llm.env` | `root:root 600` |
| Service | `/etc/systemd/system/garmin-llm.service`, a copy of [deploy/garmin-llm.service](../deploy/garmin-llm.service) | `root` |
| Sync job and timer | `/etc/systemd/system/garmin-llm-sync.{service,timer}`, copies of [deploy/](../deploy/) | `root` |
| MCP server ([garmin-mcp](https://github.com/topesonen/garmin-mcp)), a clone over HTTPS | `/opt/garmin-mcp`, with its own `.venv` | `root` (the service cannot change its code) |
| MCP settings: GitHub OAuth app, allowed GitHub user, `PUBLIC_URL`, paths | `/etc/garmin-mcp.env` | `root:root 600` |
| MCP token database (hashed tokens) | `/var/lib/garmin-mcp/tokens.sqlite` (systemd `StateDirectory`, folder `700`) | `garmin-mcp` |
| MCP service | `/etc/systemd/system/garmin-mcp.service`, a copy of garmin-mcp's `deploy/garmin-mcp.service` | `root` |

- `garmin` is a system user with no login shell. The service runs as that user, so the app can read its code and the database but cannot write to the database or read the key file. systemd reads the key file as root and passes the key in the environment.
- `garmin-sync` is a second system user, in the `garmin` group, that only runs the sync. It owns the warehouse folder, so it is the only one that can write the database; the app reads it through the group. It gets the Garmin key the same way, from `/etc/garmin-llm-sync.env`.
- The sync (`garmin-llm-sync.timer`, hourly at a random minute in the first five) runs `src/ingest_api.py`, which fetches the full history and moves a new database file into place, so the app never reads a half-written file. A failed run leaves the old database.
- The service listens on `127.0.0.1:8501` only, with systemd hardening (read-only system, no access to `/home` or `/root`).
- `tailscale serve --bg --https=8443 http://127.0.0.1:8501` puts it at `https://ubuntu-4gb-hel1-2.<tailnet>.ts.net:8443/` with a Let's Encrypt certificate that Tailscale renews. `tailscale serve status` shows "tailnet only" for 8443. Until 2026-10-23 the page was on 443; it moved so that 443 could go to the MCP server (below).
- The MCP server (`garmin-mcp.service`) runs as `garmin-mcp`, a system user without a login shell that gets the `garmin` group only inside the service (`SupplementaryGroups`), so it reads the warehouse and `docs/schema.md` and writes only its token database. It listens on `127.0.0.1:8765`, and Tailscale Funnel publishes it on the internet at `https://ubuntu-4gb-hel1-2.<tailnet>.ts.net/mcp`, behind OAuth with a GitHub login. It is on 443 because claude.ai never reached it on 8443.
- Funnel is allowed in the tailnet policy only for `tag:server` (`nodeAttrs`), and this server is the only node with that tag, so no other device can publish anything. Port 443 is the only Funnel port in use; 8443 (the page) stays tailnet only.
- Kill switch for the public MCP endpoint: `tailscale funnel --https=443 off` (nothing public any more) or `systemctl stop garmin-mcp`.
- The Hetzner firewall allows SSH from the Tailscale range only. Log in with `ssh root@<server's Tailscale IP>`.

## Routine tasks

New activities arrive within the hour. To sync at once:

```
ssh root@<server> 'systemctl start garmin-llm-sync && journalctl -u garmin-llm-sync -n 5 --no-pager -o cat'
```

The app opens the database for each query, so a restart is not needed for new data. Copying a database from the laptop is no longer needed; the next sync would replace it anyway.

When the Garmin key expires (Garmin emails about a week before), create a new one in Garmin Connect and write it as in step 4 below, to `/etc/garmin-llm-sync.env` with `GARMIN_API_KEY=`. Until then, sync runs fail and the page shows the last synced data.

After a code change is pushed:

```
ssh root@<server> 'cd /opt/garmin-llm && runuser -u garmin -- git pull && systemctl restart garmin-llm'
```

Run git as `garmin`, which owns the clone. Run as root, git stops with "detected dubious ownership".

If `requirements.txt` changed, also run `runuser -u garmin -- .venv/bin/pip install -r requirements.txt` before the restart. If a unit file in `deploy/` changed, copy it to `/etc/systemd/system/` and run `systemctl daemon-reload` first.

Checks:

```
systemctl status garmin-llm
journalctl -u garmin-llm -n 50 --no-pager
systemctl list-timers garmin-llm-sync.timer   # next and last sync
journalctl -u garmin-llm-sync -n 20 --no-pager -o cat
curl -s http://127.0.0.1:8501/_stcore/health     # on the server: ok
tailscale serve status                           # 443 Funnel on (MCP), 8443 tailnet only (page)
systemctl status garmin-mcp
journalctl -u garmin-mcp -n 50 --no-pager        # requests, no SQL or results
```

To update the MCP server after a push to garmin-mcp:

```
ssh root@<server> 'cd /opt/garmin-mcp && git pull && systemctl restart garmin-mcp'
```

## Setting it up again

1. `useradd --system --home /opt/garmin-llm --shell /usr/sbin/nologin garmin`
2. `git clone https://github.com/topesonen/garmin-llm.git /opt/garmin-llm`, then `python3 -m venv /opt/garmin-llm/.venv` and `pip install -r requirements.txt` with that venv, then `chown -R garmin:garmin /opt/garmin-llm`.
3. `useradd --system --gid garmin --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin garmin-sync`, then `install -d -o root -g garmin -m 750 /opt/garmin-llm/data`, `install -d -o garmin-sync -g garmin -m 750 /opt/garmin-llm/data/warehouse` and `install -d -o garmin-sync -g garmin -m 700 /opt/garmin-llm/data/private`. Copy `data/private/place_names.txt` from the laptop into the last one, `garmin-sync:garmin 600`.
4. Write the key file without the key appearing on screen or in shell history:
   `ssh -t root@<server> 'umask 077; read -rsp "Paste key: " k; echo; printf "ANTHROPIC_API_KEY=%s\n" "$k" > /etc/garmin-llm.env'`
   Write the Garmin key the same way, from your own terminal: `ssh -t root@<server> 'umask 077; read -rsp "Paste Garmin key: " k; echo; printf "GARMIN_API_KEY=%s\n" "$k" > /etc/garmin-llm-sync.env'`
5. Copy the three files in `deploy/` to `/etc/systemd/system/`, run `systemctl daemon-reload`, then `systemctl start garmin-llm-sync` once to build the database, and `systemctl enable --now garmin-llm garmin-llm-sync.timer`.
6. `tailscale serve --bg --https=8443 http://127.0.0.1:8501`. The first time, Tailscale asks for Serve to be enabled for the tailnet through a link; enable Serve, not Funnel.
7. MCP server: `useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin garmin-mcp`, clone garmin-mcp to `/opt/garmin-mcp` as root with its own venv, write `/etc/garmin-mcp.env` (`600`, keys listed in garmin-mcp's README; the GitHub OAuth app's callback is `https://ubuntu-4gb-hel1-2.<tailnet>.ts.net/github/callback`), copy its unit, `systemctl enable --now garmin-mcp`, then `tailscale funnel --bg --https=443 http://127.0.0.1:8765`. Funnel needs the `funnel` node attribute for `tag:server` in the tailnet policy. After Funnel is switched on, the public relays take a minute or two before they answer.
