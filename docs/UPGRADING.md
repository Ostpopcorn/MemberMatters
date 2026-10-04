# Upgrading

Notes for upgrading an existing MemberMatters instance. If you are installing for the first time, follow the [getting started](/docs/GETTING_STARTED.md) instructions instead — nothing here applies to a new install.

Database migrations run automatically every time the web container starts, so upgrading means replacing the container with one made from the new image. `docker restart` is not enough: it starts the same container again, on the image it was created from.

- **Single container**, as in the getting started instructions: follow [Updating your instance](/docs/GETTING_STARTED.md#updating-your-instance). Pull the new image, then stop, remove and re-create the container with the same `docker create` command you installed it with.
- **docker compose**: from the directory holding your [docker-compose.yml](/docker/docker-compose.yml), run:

  ```bash
  docker compose pull
  docker compose up -d
  ```

- **CapRover, Kubernetes or another setup** that runs the web app, the Celery worker and the Celery beat scheduler as separate services: move all three to the new image at the same time. Only the web app runs the migrations, and a worker or scheduler left on the old image expects the database as its own version left it. Moving the settings to a new table (django-constance 4, below) is one such change: an old worker can no longer read any setting.

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

Changes are grouped by the releases they apply to, newest first. Read every group that includes the version you are on.

## Upgrading from 3.8 or earlier

### Check the key the portal signs sign-ins with (django-oidc-provider 0.9)

If other services, such as Moodle or a wiki, let members sign in with their MemberMatters account, the portal signs those sign-ins with an RSA key stored under OpenID Connect Provider → RSA Keys in the Django admin. This release reads those keys with a stricter library. A key pasted in the OpenSSH format that `ssh-keygen` writes by default (it starts with `-----BEGIN OPENSSH PRIVATE KEY-----`), or a public key on its own, used to work and now stops every such sign-in until it is replaced.

If no other service signs in through the portal, there is nothing to do. Otherwise, check your keys before or after you upgrade. Under docker compose, replace `docker exec membermatters` with `docker compose exec mm-webapp`:

```bash
docker exec membermatters python3 manage.py shell -c "
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from oidc_provider.models import Client, RSAKey
def usable(key):
    try:
        load_pem_private_key(key.encode(), None)
        return True
    except Exception:
        return False
for key in RSAKey.objects.all():
    print('RSA key', key.id, 'is fine' if usable(key.key) else 'needs replacing')
for client in Client.objects.filter(jwt_alg='HS256', client_secret=''):
    print('Client', client.name, 'needs RS256')
"
```

For each key that needs replacing, create a new one with `docker exec membermatters python3 manage.py creatersakey`, then delete the old one in the Django admin. The services pick up the new key the next time someone signs in. A client listed as needing RS256 has no secret to sign with: set its JWT algorithm to RS256 under OpenID Connect Provider → Clients.

### Redis TLS options must be lowercase (Channels 4)

This release updates the library door, interlock and memberbucks devices use to reach Redis. If your `MM_REDIS_HOST` is a `rediss://` address with an `ssl_cert_reqs` option, write its value in lowercase: `ssl_cert_reqs=required`, `optional` or `none`. The uppercase form (`CERT_REQUIRED`) still works for background tasks, but devices can no longer connect with it, and the door buttons in Admin Tools fail.

Plain `redis://` addresses, including the one in the bundled [docker-compose.yml](/docker/docker-compose.yml), need no change.

### Database and proxy requirements (Django 5.2)

This release moves the portal from Django 3.2 to 5.2, which is stricter about two parts of your setup.

#### Newer database versions

Django 5.2 will not work with a database server older than:

| Database | Minimum |
| --- | --- |
| PostgreSQL | 14 |
| MySQL | 8.0.11 |
| MariaDB | 10.5 |

If you use SQLite (the default in the [getting started](/docs/GETTING_STARTED.md) instructions, and built into the image) or the database from the bundled [docker-compose.yml](/docker/docker-compose.yml), there is nothing to do.

If MemberMatters connects to a database server you run yourself, check its version **before** you pull the new image. This asks the running portal, so it reports the database it is actually configured to use. Under docker compose, replace `docker exec membermatters` with `docker compose exec mm-webapp`:

```bash
docker exec membermatters python3 manage.py shell -c "from django.db import connection; c = connection.cursor(); c.execute('select version()'); print(c.fetchone()[0])"
```

If the server is too old, upgrade it first. Otherwise the container still starts and the page still loads, but nobody can log in: every request that needs the database fails, and the container log shows an error such as `PostgreSQL 14 or later is required (found 13.4).` Going back to the previous image fixes it: the upgrade can't reach a database that old, so it hasn't changed any of your data.

#### Your reverse proxy must pass on X-Forwarded-Proto

Django now checks that every change a signed-in person sends — saving their profile, logging in to the Django admin — comes from the same address the portal is served at. When a reverse proxy handles HTTPS for you, the portal only knows it is being reached over HTTPS if the proxy says so in the `X-Forwarded-Proto` header. If the proxy leaves it out, that check fails: members can still log in, but nothing they save goes through, and the Django admin login answers with "CSRF verification failed". Each failed admin login leaves a line like this in the container log:

```
Forbidden (Origin checking failed - https://portal.example.org does not match any trusted origins.): /admin/login/
```

If you set up nginx as described in [Post Installation Steps](/docs/POST_INSTALL_STEPS.md) and nothing sits in front of it, your proxy already sends the header and there is nothing to do. Otherwise, check your proxy's configuration before you upgrade. For nginx, the location that forwards to MemberMatters needs both of these lines; other proxies have an equivalent setting:

```nginx
proxy_set_header Host $http_host;
proxy_set_header X-Forwarded-Proto $scheme;
```

`$http_host` keeps the port when the portal's address has one, such as `https://portal.example.org:8443`. The `$host` in Post Installation Steps drops it, which works only on the standard ports 80 and 443.

**Cloudflare in front of your proxy.** Cloudflare tells your proxy in `X-Forwarded-Proto` whether the visitor used HTTPS. In its Flexible SSL mode, though, it connects to your proxy over plain HTTP, so the `$scheme` line above replaces that `https` with `http` and the check fails. In the Cloudflare dashboard, under SSL/TLS → Overview, set the encryption mode to Full (strict): Cloudflare then connects to your proxy over HTTPS, which needs a certificate from a public authority such as the one certbot set up in Post Installation Steps. If Cloudflare has to reach your proxy over plain HTTP, for example through a Cloudflare Tunnel to an `http://` address, and every request comes through Cloudflare, pass on its header instead:

```nginx
proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
```

### Settings move to a new table and format (django-constance 4)

The settings you edit in the Django admin, under Constance → Config, are stored in a single table, which used to be named `constance_config`. django-constance moves those rows into a table named `constance_constance` and drops the old one. It then converts each saved value from Python's pickle format to JSON.

There is nothing for you to do. The migration copies every row across and converts it, so your settings — including API keys, Stripe configuration and email templates — keep their values.

The conversion can't be undone. To go back to an older version after upgrading, restore the backup you took first. Older versions don't understand the converted settings.

If you want to check, count the settings that have a value before you upgrade:

```bash
docker exec membermatters python3 manage.py shell -c "from django.db import connection; c = connection.cursor(); c.execute('select count(*) from constance_config where value is not null'); print(c.fetchone()[0])"
```

and count them again in the new container:

```bash
docker exec membermatters python3 manage.py shell -c "from django.db import connection; c = connection.cursor(); c.execute('select count(*) from constance_constance'); print(c.fetchone()[0])"
```

Under docker compose, replace `docker exec membermatters` with `docker compose exec mm-webapp`.

The second number should be at least the first. It can be higher, because the portal saves a setting's default the first time it reads one that was never saved. If it is lower, restore your backup rather than re-entering the settings by hand.

The first count leaves out settings stored without a value. The upgrade deletes those, and the portal saves their default the next time it reads them.

### Dashboard cards move to Admin Tools

Older versions configured the member dashboard through a setting named `HOME_PAGE_CARDS`. It is replaced by the Dashboard Cards editor under Admin Tools, and the upgrade creates a card for each entry in your old setting, so your dashboard looks the same afterwards.

If the setting isn't valid JSON, no cards are imported and the container log says so. Enter them under Admin Tools → Dashboard Cards instead.

### The phone app and the installable web app are removed

This release removes two ways of building the portal that were never finished or kept up to date:

- **The iOS and Android app** (built with Capacitor). Each makerspace had to build and publish its own copy to the app stores, and its project files had not been updated since 2023.
- **The installable web app (PWA) mode.** It was never finished and could not be built.

Members keep using the portal in their phone's browser, which works as before. If your members use a browser or a kiosk, there is nothing to do.

If your makerspace published its own MemberMatters app, it can no longer be built from this release. This release changes nothing on the server that those apps use, but once you turn on CAPTCHA, members can no longer sign in to them, so plan to retire the app.

If you left the `CAPTCHA_ALLOWED_HOSTNAMES` setting empty because of the app, you can now fill it in with your portal's hostname. [Post Installation Steps](/docs/POST_INSTALL_STEPS.md) explains what it protects against.

### Kiosks need a 64-bit system (Electron 44)

The kiosk app ([Kiosk Mode](/docs/GETTING_STARTED.md#kiosk-mode)) now runs on Electron 44. Electron 26, which it used before, stopped getting security fixes in February 2024. If you only run the Docker image and have no kiosk, there is nothing to do.

- Electron 44 only exists for 64-bit systems. A kiosk on a 32-bit operating system, such as 32-bit Raspberry Pi OS or 32-bit Windows, can't run it. On a Raspberry Pi 3 or later, install the 64-bit Raspberry Pi OS, then build the kiosk again. On a Mac it needs macOS 13 or later.
- Building the kiosk needs Node 22, version 22.22 or later, for example `nvm install 22`.
- On a Wayland desktop, such as Raspberry Pi OS since Bookworm, the kiosk now runs as a native Wayland app. X11 tools in its startup script, such as `unclutter` or `xdotool`, no longer reach its window. Start it with `--ozone-platform=x11` to keep the old behaviour.
- The packaged kiosk now keeps its files in a single `resources/app.asar` archive instead of a `resources/app` folder. If you used to change files in that folder after building, make the change in the source instead and build again.

### Members need a browser from 2022 or later

This release moves the portal to a newer version of its interface library, Quasar 2.34. It uses browser features that older versions lack, so the login page and the rest of the portal no longer work in:

- Chrome or Edge older than version 93
- Firefox older than version 92
- Safari older than version 15.4, which includes iPhones and iPads that haven't been updated to iOS 15.4 or later

Chrome, Edge and Firefox normally update themselves, and every device that runs iOS 15 can install 15.4 or later, so few members should notice. A member who can't log in after the upgrade should update their browser or device. In browsers older than Chrome 111, Firefox 113 or Safari 16.2, shadows look flat, but everything else works. Kiosks are not affected: they bring their own browser.
