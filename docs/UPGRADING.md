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
