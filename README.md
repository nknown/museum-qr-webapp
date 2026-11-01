# Museum in Your Pocket

Museum in Your Pocket (MIYP) is a Django and Wagtail platform for museum
visitors to access exhibition content through QR codes and mobile devices. It
also provides presentation, interaction, and analytics tools for curators.

## Run with Docker

1. Create a local environment file:

   ```bash
   cp MIYP/.env.example MIYP/.env
   ```

2. Replace every placeholder in `MIYP/.env`. Generate independent random
   values for `MAIN_APP_SECRET` and `POSTGRES_DB_PASSWORD`; never commit this
   file.

3. Build the services and prepare the database:

   ```bash
   docker compose --env-file MIYP/.env build
   docker compose --env-file MIYP/.env up -d db
   docker compose --env-file MIYP/.env run --rm web python manage.py migrate
   docker compose --env-file MIYP/.env run --rm web python manage.py createsuperuser
   ```

4. Start the application:

   ```bash
   docker compose --env-file MIYP/.env up
   ```

The reverse proxy serves the application over HTTPS on port `8000`. The local
certificate is self-signed, so a browser warning is expected in development.

## Tests

With the dependencies and environment configured:

```bash
python manage.py test
```

## Project layout

- `MIYP/` — Django project settings, URLs, middleware, and translations.
- `main_app/` — museum models, views, templates, administration, and tests.
- `MIYP_maps/` — map views and frontend assets.
- `docker/` — application and Nginx container configuration.
- `Feeder/` — local import drop folder; imported data is intentionally ignored.

## Security

Only `MIYP/.env.example` is tracked. Real environment files, databases,
uploaded media, certificates, private keys, and generated static files are
ignored. If a credential is ever committed, revoke or rotate it immediately;
deleting the file in a later commit does not remove it from Git history.
