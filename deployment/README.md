# University deployment

This directory contains the hardened deployment profile derived from the
configuration used for the thesis evaluation. It is separate from the root
`docker-compose.yml`, which remains the convenient development environment.

The profile runs three services:

- `web`: MIYP under Daphne/ASGI as an unprivileged user;
- `db`: PostgreSQL on a private internal network;
- `nginx`: the HTTPS ingress, static/media server, and request policy boundary.

There is no workstation-specific OAuth bridge. Authentication callbacks use
the real university HTTPS origin registered with the identity provider.

Nginx remains as the ordinary HTTPS ingress because it terminates TLS, serves
static and permitted media from read-only volumes, and enforces the media and
request policies. If the university requires its own ingress instead, that
managed gateway must reproduce these controls; Daphne should not be published
directly as a replacement for them.

## Prerequisites

- A DNS hostname assigned to the server, such as `miyp.example.edu`.
- TCP ports 80 and 443 available to the deployment.
- Docker Engine with the Compose plugin.
- Python 3 and OpenSSL for one-time configuration.
- A certificate chain and private key issued for the assigned hostname.

PostgreSQL is not published on a host port. Do not expose port 5432.

## Configure

From the repository root, create the private configuration once:

```bash
python3 deployment/configure.py --origin https://miyp.example.edu
```

This creates `deployment/deployment.env` with mode `0600`, random application
and database secrets, explicit allowed hosts, and conservative initial
connection limits. It refuses to overwrite an existing file so an accidental
rerun cannot rotate secrets and disconnect the deployment from its database.

Install the university certificate using the filenames expected by Nginx:

```bash
install -m 0644 /secure/path/fullchain.pem deployment/tls/fullchain.pem
install -m 0600 /secure/path/privkey.pem deployment/tls/privkey.pem
```

For an isolated lab test only, `configure.py` accepts `--self-signed`. Do not
use that option for the final university service.

Private configuration and TLS material are excluded from Git and Docker build
contexts. Never commit them.

## Initialise

Build the immutable application image and initialise persistent storage:

```bash
deployment/compose.sh build
deployment/compose.sh up -d db
deployment/compose.sh run --rm web python manage.py migrate
deployment/compose.sh run --rm web python manage.py collectstatic --noinput
deployment/compose.sh run --rm web python manage.py createsuperuser
deployment/compose.sh up -d
```

The migration and static-collection steps are explicit. They are not repeated
every time a container starts.

Import all curated spreadsheets from `Feeder/` after the superuser exists:

```bash
deployment/compose.sh exec web python manage.py feeder_import
```

The command assigns imported museums and exhibitions to superusers.

## Verify

```bash
deployment/compose.sh ps
deployment/compose.sh logs --tail 100 web nginx db
curl --fail https://miyp.example.edu/health/ready/
```

Open `https://miyp.example.edu/cms/`, authenticate as the superuser, and verify
that a published User Device presentation works from a separate browser or
phone on the intended network.

## Google authentication

Register this exact redirect URI in the Google OAuth web client:

```text
https://miyp.example.edu/complete/google-oauth2/
```

Then update the private `deployment/deployment.env`:

```dotenv
MAIN_APP_GOOGLE_OAUTH=on
SOCIAL_AUTH_GOOGLE_OAUTH2_KEY=replace-with-client-id
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET=replace-with-client-secret
```

Recreate the web container so it receives the new environment:

```bash
deployment/compose.sh up -d --force-recreate web
```

The redirect uses the registered public origin directly. No localhost or
workstation-hostname rewriting is performed.

## Security controls

The deployment profile:

- requires production mode, PostgreSQL, a strong secret, and explicit hosts;
- runs the application as UID/GID 10001 with a read-only root filesystem;
- drops application container capabilities and prevents privilege escalation;
- places PostgreSQL on an internal Docker network;
- mounts static and media volumes read-only in Nginx;
- serves Wagtail documents through `/documents/` rather than their storage path;
- blocks `/images/documents/` and active HTML, SVG, XML, or JavaScript uploads;
- applies secure cookies, HTTPS redirects, HSTS, `nosniff`, and same-origin
  framing/referrer policies;
- limits login attempts at Nginx and records request timing without client IPs,
  query strings, or cookies;
- uses health checks for PostgreSQL, the application schema, and Nginx.

The telemetry limit is observation-only by default. `TELEMETRY_LIMIT_DRY_RUN`
must be changed deliberately before it can reject slide-tracking requests.

The initial PostgreSQL/application limits are 100 connections and 75 admitted
HTTP requests. They are conservative defaults, not measured capacity claims.
Tune them only after measuring the assigned server and preserving room for
health checks and administration.

## Persistence and backups

`down` preserves the named database, static, and media volumes:

```bash
deployment/compose.sh down
```

Never add `-v` unless permanent deletion is intended.

Create a PostgreSQL custom-format backup and matching media archive:

```bash
mkdir -p deployment/backups
deployment/compose.sh exec -T db \
  pg_dump -U miyp_user -d miyp_database -Fc \
  > deployment/backups/database.dump
deployment/compose.sh run --rm -T --no-deps web \
  tar -cf - -C /app/main_app/media . \
  > deployment/backups/media.tar
```

Keep backups and `deployment.env` under access control outside Git.

## Update

After reviewing and pulling a new release:

```bash
git pull --ff-only
deployment/compose.sh build
deployment/compose.sh run --rm web python manage.py migrate
deployment/compose.sh run --rm web python manage.py collectstatic --noinput
deployment/compose.sh up -d
deployment/compose.sh ps
```

Take a database/media backup before applying an update.
