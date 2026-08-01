# Production deployment

Cashbook is designed to run behind a host-managed HTTPS reverse proxy at
`cashbook.mafunami.me`. PostgreSQL is never published to the host network.
The production Compose file binds only the frontend and backend to `127.0.0.1`;
the host Nginx process is the sole internet-facing component.

## First deployment

1. Copy `.env.production.example` to `.env`, replace its placeholders, and
   restrict it: `chmod 600 .env`. The file contains secrets and must not be
   committed.
2. Validate the non-secret runtime configuration:

   ```bash
   docker compose --env-file .env -f compose.production.yaml --profile migration run --rm migrate
   ```

   This validates production settings and runs Alembic migrations against the
   persistent `cashbook-postgres-production-data` volume.
3. Start the services:

   ```bash
   docker compose --env-file .env -f compose.production.yaml up --build -d
   ```
4. Verify from the host:

   ```bash
   curl --fail http://127.0.0.1:8000/health
   curl --fail http://127.0.0.1:8000/ready
   curl --fail http://127.0.0.1:8080/
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

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

The backend enables Uvicorn proxy-header processing. `FORWARDED_ALLOW_IPS=*`
is acceptable only in this topology because the backend port is loopback-only;
if that exposure changes, replace it with the precise trusted proxy address.
`FRONTEND_ORIGIN` and `TRUSTED_HOSTS` must both name the HTTPS public host.

## Operational checks

Use `docker compose --env-file .env -f compose.production.yaml ps` to inspect
container health. The liveness endpoint checks the API process; `/ready` also
checks PostgreSQL. Do not expose either service port through a public firewall
rule.
