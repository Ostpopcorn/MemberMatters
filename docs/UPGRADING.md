# Upgrading

Notes for upgrading an existing MemberMatters instance. If you are installing for the first time, follow the [getting started](/docs/GETTING_STARTED.md) instructions instead — nothing here applies to a new install.

Database migrations run automatically every time the web container starts, so an upgrade is normally just pulling the new image and restarting it:

```bash
docker pull membermatters/membermatters
docker restart membermatters
```

**Back up your database first.** Some upgrades move data between tables and drop the old one, and downgrading will not undo that. Run this from the directory holding your [docker-compose.yml](/docker/docker-compose.yml), where `mm-postgres` is the database service:

```bash
docker compose exec -T mm-postgres pg_dump -U membermatters membermatters > membermatters-backup.sql
```

Sections are newest first. Read the ones between the version you are on and the version you are moving to.

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

## Settings move to a new table (django-constance 3.1)

Everything you edit under Admin Tools is stored in a single table, which used to be named `constance_config`. django-constance 3.1 moves those rows into a table named `constance_constance` and drops the old one.

There is nothing for you to do. The migration copies every row across, so your settings — including API keys, Stripe configuration and email templates — are preserved.

If you want to check, count the rows before you upgrade:

```bash
docker compose exec mm-postgres psql -U membermatters -d membermatters -c "select count(*) from constance_config;"
```

and count them again afterwards:

```bash
docker compose exec mm-postgres psql -U membermatters -d membermatters -c "select count(*) from constance_constance;"
```

The two numbers should be the same. The copy is a single statement that either moves everything or nothing, so if the new table is empty, restore your backup and try again rather than re-entering the settings by hand.

### Dashboard cards are not imported if you skip past their release

Older versions configured the member dashboard through a setting named `HOME_PAGE_CARDS`. When the Dashboard Cards editor was added to Admin Tools, a one-time migration came with it that reads that setting and creates a card for each entry.

That import cannot run while the settings are being moved to the new table. So it is skipped if you upgrade from a version older than the Dashboard Cards editor directly to this version or a later one — your dashboard will show the default cards instead of your own.

Nothing is lost. The old setting is still in the database, so you can copy your cards out of it and recreate them. Open a shell in the web container:

```bash
docker exec -it membermatters bash
python3 manage.py shell
```

and print the old value:

```python
from constance.models import Constance
row = Constance.objects.filter(key="HOME_PAGE_CARDS").first()
print(row.value if row else "nothing saved")
```

Then enter the cards under Admin Tools → Dashboard Cards. There is no way to trigger the import afterwards.

To avoid this altogether, upgrade in two steps: first to a version that has the Dashboard Cards editor but not this settings change, let the container start and finish migrating, then upgrade the rest of the way.
