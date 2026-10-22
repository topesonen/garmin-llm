# Server

The page runs on a small Hetzner server (`ubuntu-4gb-hel1-2`: Ubuntu 24.04, 2 vCPU, 4 GB RAM) and is reachable over HTTPS from Topias's Tailscale devices only. Set up on 2026-10-19 (M3).

## Layout

| What | Where | Owner, mode |
|---|---|---|
| Code, a clone of this repo over HTTPS | `/opt/garmin-llm` | `garmin` |
| Virtual environment | `/opt/garmin-llm/.venv` | `garmin` |
| Database | `/opt/garmin-llm/data/warehouse/garmin.duckdb` | `root:garmin 640` |
| API key (`ANTHROPIC_API_KEY=...`, its own key) | `/etc/garmin-llm.env` | `root:root 600` |
| Service | `/etc/systemd/system/garmin-llm.service`, a copy of [deploy/garmin-llm.service](../deploy/garmin-llm.service) | `root` |

- `garmin` is a system user with no login shell. The service runs as that user, so the app can read its code and the database but cannot write to the database or read the key file. systemd reads the key file as root and passes the key in the environment.
- The service listens on `127.0.0.1:8501` only, with systemd hardening (read-only system, no access to `/home` or `/root`).
- `tailscale serve --bg 8501` puts it at `https://ubuntu-4gb-hel1-2.<tailnet>.ts.net/` with a Let's Encrypt certificate that Tailscale renews. `tailscale serve status` shows "tailnet only". Funnel (public internet) is not used, and the `funnel` attribute was removed from the tailnet policy, so it cannot be turned on by accident.
- The Hetzner firewall allows SSH from the Tailscale range only. Log in with `ssh root@<server's Tailscale IP>`.

## Routine tasks

After a new ingest on the laptop, copy the database and restart:

```
scp data/warehouse/garmin.duckdb root@<server>:/opt/garmin-llm/data/warehouse/garmin.duckdb
ssh root@<server> 'chown root:garmin /opt/garmin-llm/data/warehouse/garmin.duckdb && chmod 640 /opt/garmin-llm/data/warehouse/garmin.duckdb'
```

The app opens the database for each query, so a restart is not needed for new data.

After a code change is pushed:

```
ssh root@<server> 'cd /opt/garmin-llm && runuser -u garmin -- git pull && systemctl restart garmin-llm'
```

If `requirements.txt` changed, also run `runuser -u garmin -- .venv/bin/pip install -r requirements.txt` before the restart. If the service file changed, copy it to `/etc/systemd/system/` and run `systemctl daemon-reload` first.

Checks:

```
systemctl status garmin-llm
journalctl -u garmin-llm -n 50 --no-pager
curl -s http://127.0.0.1:8501/_stcore/health     # on the server: ok
tailscale serve status
```

## Setting it up again

1. `useradd --system --home /opt/garmin-llm --shell /usr/sbin/nologin garmin`
2. `git clone https://github.com/topesonen/garmin-llm.git /opt/garmin-llm`, then `python3 -m venv /opt/garmin-llm/.venv` and `pip install -r requirements.txt` with that venv, then `chown -R garmin:garmin /opt/garmin-llm`.
3. `install -d -o root -g garmin -m 750 /opt/garmin-llm/data /opt/garmin-llm/data/warehouse`, then copy the database as above.
4. Write the key file without the key appearing on screen or in shell history:
   `ssh -t root@<server> 'umask 077; read -rsp "Paste key: " k; echo; printf "ANTHROPIC_API_KEY=%s\n" "$k" > /etc/garmin-llm.env'`
5. Copy `deploy/garmin-llm.service` to `/etc/systemd/system/`, then `systemctl daemon-reload && systemctl enable --now garmin-llm`.
6. `tailscale serve --bg 8501`. The first time, Tailscale asks for Serve to be enabled for the tailnet through a link; enable Serve, not Funnel.
