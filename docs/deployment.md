# Production deployment

Cashbook is designed to run behind a host-managed HTTPS reverse proxy at
`cashbook.mafunami.me`. PostgreSQL is never published to the host network.
The backend remains on `127.0.0.1`. The frontend binds to loopback, the home
server's LAN address, and its Tailscale address so the remote VPS can bridge
HTTPS traffic over the tailnet without exposing the service on every host
interface.

## First deployment

1. Copy `.env.production.example` to `.env.prod`, replace its placeholders,
   and restrict it: `chmod 600 .env.prod`. The file contains secrets and must
   not be committed. Using a distinct filename prevents development and
   production settings from being mixed accidentally.
2. Validate the non-secret runtime configuration:

   ```bash
   docker compose --env-file .env.prod -f compose.production.yaml --profile migration run --rm migrate
   ```

   This validates production settings and runs Alembic migrations against the
   persistent `cashbook-postgres-production-data` volume.
3. Start the services:

   ```bash
   docker compose --env-file .env.prod -f compose.production.yaml up --build -d
   ```
4. Verify from the host:

   ```bash
   curl --fail http://127.0.0.1:8002/health
   curl --fail http://127.0.0.1:8002/ready
   curl --fail http://127.0.0.1:3004/
   curl --fail http://192.168.2.2:3004/
   curl --fail http://100.93.39.106:3004/
   test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
     -H 'Host: cashbook.mafunami.me' http://127.0.0.1:3004/api/v1/auth/session)" = 401
   ```

The database volume persists through `docker compose down`; only an explicit
volume removal deletes it.

## Nginx HTTPS reverse proxy

Install and manage TLS certificates on the host (for example, with Certbot).
Do not copy certificate private keys into this repository or a container.

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name cashbook.mafunami.me;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name cashbook.mafunami.me;

    ssl_certificate /etc/letsencrypt/live/cashbook.mafunami.me/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/cashbook.mafunami.me/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        proxy_pass http://100.93.39.106:3004;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

The production frontend proxies `/api/` to the backend across the private
Compose network, so the VPS needs only the `100.93.39.106:3004` Tailscale
upstream. On this deployment, `100.93.39.106` is the home server and
`100.76.69.118` is the VPS (`phishy-droplet`). Tailnet ACLs should allow only
the VPS to reach TCP port 3004 when possible. The backend's host port remains
loopback-only for health checks. `FRONTEND_ORIGIN` must name the HTTPS public
host; `TRUSTED_HOSTS` additionally includes the internal addresses used for
health checks and direct LAN/Tailscale routing.

## Operational checks

Use `docker compose --env-file .env.prod -f compose.production.yaml ps` to inspect
container health. The liveness endpoint checks the API process; `/ready` also
checks PostgreSQL. Do not expose either service port through a public firewall
rule.
