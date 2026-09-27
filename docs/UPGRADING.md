# Upgrading

Notes for upgrading an existing MemberMatters instance. If you are installing for the first time, follow the [getting started](/docs/GETTING_STARTED.md) instructions instead — nothing here applies to a new install.

Database migrations run automatically every time the web container starts, so upgrading means replacing the container with one made from the new image. `docker restart` is not enough: it starts the same container again, on the image it was created from.

- **Single container**, as in the getting started instructions: follow [Updating your instance](/docs/GETTING_STARTED.md#updating-your-instance). Pull the new image, then stop, remove and re-create the container with the same `docker create` command you installed it with.
- **docker compose**: from the directory holding your [docker-compose.yml](/docker/docker-compose.yml), run:

  ```bash
  docker compose pull
  docker compose up -d
  ```

**Back up your database first.** Some upgrades move or convert data, and going back to the previous image does not undo that.

- **SQLite**, the getting started default: stop the container and copy the database file out of the folder you mounted, which is `/usr/app/` in the getting started instructions. Then carry on with the upgrade.

  ```bash
  docker stop membermatters
  cp /usr/app/db.sqlite3 /usr/app/db.sqlite3.backup
  ```

- **PostgreSQL under docker compose**, where `mm-postgres` is the database service:

  ```bash
  docker compose exec -T mm-postgres pg_dump -U membermatters membermatters > membermatters-backup.sql
  ```

- **A database server you run yourself**: use its own backup tool, such as `pg_dump` or `mysqldump`.

Sections are newest first. Read the ones between the version you are on and the version you are moving to.

## Redis TLS options must be lowercase (Channels 4)

This release updates the library door, interlock and memberbucks devices use to reach Redis. If your `MM_REDIS_HOST` is a `rediss://` address with an `ssl_cert_reqs` option, write its value in lowercase: `ssl_cert_reqs=required`, `optional` or `none`. The uppercase form (`CERT_REQUIRED`) still works for background tasks, but devices can no longer connect with it, and the door buttons in Admin Tools fail.

Plain `redis://` addresses, including the one in the bundled [docker-compose.yml](/docker/docker-compose.yml), need no change.

## Database and proxy requirements (Django 4.2)

This release moves the portal onto Django 4.2, which is stricter about two parts of your setup.

### Newer database versions

Django 4.2 will not work with a database server older than:

| Database | Minimum |
| --- | --- |
| PostgreSQL | 12 |
| MySQL | 8 |
| MariaDB | 10.4 |

If you use SQLite (the default in the [getting started](/docs/GETTING_STARTED.md) instructions, and built into the image) or the database from the bundled [docker-compose.yml](/docker/docker-compose.yml), there is nothing to do.

If MemberMatters connects to a database server you run yourself, check its version **before** you pull the new image. This asks the running portal, so it reports the database it is actually configured to use. Under docker compose, replace `docker exec membermatters` with `docker compose exec mm-webapp`:

```bash
docker exec membermatters python3 manage.py shell -c "from django.db import connection; c = connection.cursor(); c.execute('select version()'); print(c.fetchone()[0])"
```

If the server is too old, upgrade it first. Otherwise the container still starts and the page still loads, but nobody can log in: every request that needs the database fails, and the container log shows an error such as `PostgreSQL 12 or later is required`. Going back to the previous image fixes it, because this upgrade makes no changes to your data.

### Your reverse proxy must pass on X-Forwarded-Proto

Django 4.2 checks that every change a signed-in person sends — saving their profile, logging in to the Django admin — comes from the same address the portal is served at. When a reverse proxy handles HTTPS for you, the portal only knows it is being reached over HTTPS if the proxy says so in the `X-Forwarded-Proto` header. If the proxy leaves it out, that check fails: members can still log in, but nothing they save goes through, and the Django admin login answers with "CSRF verification failed". Each failed admin login leaves a line like this in the container log:

```
Forbidden (Origin checking failed - https://portal.example.org does not match any trusted origins.): /admin/login/
```

If you set up nginx as described in [Post Installation Steps](/docs/POST_INSTALL_STEPS.md), your proxy already sends the header and there is nothing to do. Otherwise, check your proxy's configuration before you upgrade. For nginx, the location that forwards to MemberMatters needs both of these lines; other proxies have an equivalent setting:

```nginx
proxy_set_header Host $host;
proxy_set_header X-Forwarded-Proto $scheme;
```

## Settings move to a new table and format (django-constance 4)

The settings you edit in the Django admin, under Constance → Config, are stored in a single table, which used to be named `constance_config`. django-constance moves those rows into a table named `constance_constance` and drops the old one. It then converts each saved value from Python's pickle format to JSON.

There is nothing for you to do. The migration copies every row across and converts it, so your settings — including API keys, Stripe configuration and email templates — keep their values.

The conversion can't be undone. To go back to an older version after upgrading, restore the backup you took first. Older versions don't understand the converted settings.

If you want to check, count the rows before you upgrade:

```bash
docker exec membermatters python3 manage.py shell -c "from django.db import connection; c = connection.cursor(); c.execute('select count(*) from constance_config'); print(c.fetchone()[0])"
```

and count them again in the new container:

```bash
docker exec membermatters python3 manage.py shell -c "from django.db import connection; c = connection.cursor(); c.execute('select count(*) from constance_constance'); print(c.fetchone()[0])"
```

Under docker compose, replace `docker exec membermatters` with `docker compose exec mm-webapp`.

The second number should be at least the first. It can be higher, because the portal saves a setting's default the first time it reads one that was never saved. If it is lower, restore your backup rather than re-entering the settings by hand.

## Dashboard cards move to Admin Tools

Older versions configured the member dashboard through a setting named `HOME_PAGE_CARDS`. It is replaced by the Dashboard Cards editor under Admin Tools, and the upgrade creates a card for each entry in your old setting, so your dashboard looks the same afterwards.

If the setting isn't valid JSON, no cards are imported and the container log says so. Enter them under Admin Tools → Dashboard Cards instead.
