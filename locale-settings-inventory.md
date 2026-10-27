# Locale, time zone and location settings: inventory

Everywhere MemberMatters sets, defaults or hard-codes a language, time zone,
currency, number/date format or physical location, as of `dev` at `343b042`
(v4.0.0). The goal is to have one list to work from when consolidating these
settings.

Line numbers are for that commit.

## At a glance

| Concern | Set by | Where | Default | Read by |
|---|---|---|---|---|
| Server language | env `MM_LANGUAGE_CODE` → `LANGUAGE_CODE` | `memberportal/membermatters/settings.py:428` | `en-au` | Django admin, DRF messages, anything rendered outside a `translation.override` |
| Server time zone | env `MM_TIME_ZONE` → `TIME_ZONE` | `memberportal/membermatters/settings.py:430` | `Australia/Brisbane` | Dates in emails, Django admin, naive datetimes from clients |
| Member email language | constance `EMAIL_LANGUAGE` | `memberportal/membermatters/constance_config.py:47` (choices at `:5`) | `en-AU` | `services/email_i18n.py` |
| Admin email language | hard-coded `ADMIN_EMAIL_LANGUAGE = ENGLISH` | `memberportal/services/email_i18n.py:14-15` | `en-AU` | admin, memberbucks, meeting proxy, device emails |
| Frontend UI language | browser `navigator.language` | `src-frontend/src/boot/i18n.ts:8` | none (browser) | all `$t()` strings |
| Frontend fallback language | hard-coded | `src-frontend/src/boot/i18n.ts:9` | `en-AU` | vue-i18n |
| Quasar component strings | hard-coded language pack | `src-frontend/quasar.config.js:179` | `en-US` | QTable, QDate and similar, plus `<html lang>` |
| Currency **display** | constance `SITE_LOCALE_CURRENCY` | `memberportal/membermatters/constance_config.py:24` | `en-AU` (→ AUD) | every `$n(…, 'currency', siteLocaleCurrency)` |
| Currency **charged**, membership | `PaymentPlan.currency`, per plan | `memberportal/api_admin_tools/models.py:55` | `aud` | Stripe prices |
| Currency **charged**, memberbucks | constance `MEMBERBUCKS_CURRENCY` | `memberportal/membermatters/constance_config.py:266` | `aud` | Stripe PaymentIntent |
| Phone number region | constance `PROFILE_DEFAULT_PHONE_REGION` | `memberportal/membermatters/constance_config.py:407` | `AU` | backend `to_e164()`, frontend phone fields |
| Postal address (emails) | constance `SITE_MAIL_ADDRESS` | `memberportal/membermatters/constance_config.py:52` | `123 Example St, Nowhere` | email footers, `/api/config` `contact.address` |
| Postal address and coordinates (SpaceAPI) | constance `SPACE_DIRECTORY_LOCATION_ADDRESS` / `_LAT` / `_LON` | `memberportal/membermatters/constance_config.py:237-242` | `123 Setme St`, `0.0`, `0.0` | `/api/spacedirectory` |
| Celery time zone | not set | `memberportal/membermatters/settings.py:449-452` | UTC (Celery default) | Celery beat crontab schedules |
| Container OS time zone and locale | not set | `docker/Dockerfile` | UTC / POSIX | naive `datetime.now()`, process logs |
| Frontend date formats | hard-coded dayjs format strings, no dayjs locale loaded | `src-frontend/src/mixins/formatMixin.ts` and others (below) | Australian-style English | every date shown in the UI |

In the Django admin (Constance → Config) the locale-related settings are spread
across five fieldsets: **General** (`SITE_LOCALE_CURRENCY`), **Contact
Information** (`EMAIL_LANGUAGE`, `SITE_MAIL_ADDRESS`), **Member Profile**
(`PROFILE_DEFAULT_PHONE_REGION`), **Stripe (PAYMENT GATEWAY) Integration**
(`MEMBERBUCKS_CURRENCY`) and **Space Directory** (location). Language and time
zone for the server are environment variables, not Constance settings, and the
plan currency is a per-plan field under Admin Tools.

## Backend (Django)

### Language

- `memberportal/membermatters/settings.py:428`: `LANGUAGE_CODE = os.getenv("MM_LANGUAGE_CODE", "en-au")`.
- `memberportal/membermatters/settings.py:431`: `USE_I18N = True`.
- `memberportal/membermatters/settings.py:435`: `LOCALE_PATHS = [BASE_DIR/locale]`. The only catalog is `memberportal/locale/sv/LC_MESSAGES/django.po`; English is the msgid source and has no catalog.
- There is no `LocaleMiddleware` in `MIDDLEWARE` (`settings.py:113-126`), so every request runs in `LANGUAGE_CODE`. The browser's `Accept-Language` is ignored on the backend.
- `memberportal/membermatters/settings_test.py:92`: tests pin `LANGUAGE_CODE = "en-au"`.

### Time zone

- `memberportal/membermatters/settings.py:430`: `TIME_ZONE = os.getenv("MM_TIME_ZONE", "Australia/Brisbane")`.
- `memberportal/membermatters/settings.py:432`: `USE_TZ = True`. The database stores UTC.
- `memberportal/membermatters/settings.py:378-381`: the default DRF renderer is `UTCJSONRenderer`, so the API always sends ISO 8601 UTC (`…Z`).
- `memberportal/membermatters/dates.py`: the API's date helpers:
  - `to_utc_iso()` (`:25`) treats naive datetimes as `TIME_ZONE` wall-clock.
  - `parse_client_datetime()` (`:46`) treats a client datetime with no offset as `TIME_ZONE` wall-clock. Used by `api_meeting/views.py`.
  - `format_local_datetime()` (`:60`) formats in `TIME_ZONE` using the active language's `DATETIME_FORMAT`. Used for meeting proxy emails (`api_meeting/views.py:133,146,168,181`).
- `memberportal/api_billing/stripe_utils.py:56-68`: `format_invoice_due_date()` converts Stripe's Unix due date to `TIME_ZONE` and formats it as `"j F Y"` in the active language.
- `memberportal/api_billing/stripe_utils.py:71-96`: `format_invoice_amount()` uses `number_format` in the active language plus Stripe's ISO currency code (e.g. `12,50 AUD` in Swedish).
- `memberportal/api_admin_tools/views.py:327-345`: converts the Stripe period end from UTC and compares it with `timezone.now()`. Correct, and needs no settings.
- `memberportal/api_access/consumers.py:68,102`: naive `datetime.datetime.now()` (container OS time zone). Used only to log how long a device was connected, so harmless, but it's the one call that bypasses Django's time zone.
- Tests don't pin `TIME_ZONE` in `settings_test.py`, so they inherit `MM_TIME_ZONE` from `.env` (the same issue the comment at `settings_test.py:88-91` describes for language). `api_billing/tests/test_webhook_email_language.py:159-167` works around it by pinning UTC itself.

### Emails

- `memberportal/services/email_i18n.py`: `ENGLISH = "en-AU"`. `ADMIN_EMAIL_LANGUAGE = ENGLISH`. `member_email_language()` returns `config.EMAIL_LANGUAGE`, which is site-wide (the function takes a `user` so a per-member preference could slot in later).
- `memberportal/membermatters/constance_config.py:5`: `EMAIL_LANGUAGES = (("en-AU", "English"), ("sv-SE", "Svenska"))`. A new language needs to be added here and needs a catalog.
- `memberportal/services/emails.py:34`: every template renders under `translation.override(language)`, where `language` is a required argument.
- Callers that pin English: `api_access/consumers.py:553,626`, `api_meeting/views.py:142,152,177,…`, `api_billing/webhook_handlers.py:125,202`.
- Email templates (`memberportal/profile/templates/email_*.html`) write the active language to `<html lang>` and put `SITE_MAIL_ADDRESS` in the footer.

### Currency

- `memberportal/api_admin_tools/models.py:55-56`: `PaymentPlan.currency`, "Three letter ISO currency code", default `"aud"` (migration `api_admin_tools/migrations/0004_paymentplan_currency.py`).
- `memberportal/api_admin_tools/views.py:1147,1161`: the plan currency comes from free-text admin input, lower-cased and not validated.
- `memberportal/membermatters/constance_config.py:266`: `MEMBERBUCKS_CURRENCY = "aud"`, used in `api_member_bucks/views.py:89`.
- `memberportal/membermatters/constance_config.py:265`: `MEMBERBUCKS_MAX_TOPUP` is described as "in dollars".
- `memberportal/membermatters/constance_config.py:130`: `STRIPE_MEMBERBUCKS_TOPUP_OPTIONS = "[1000, 2000, 3000]"` (cents). The API sends it (`api_general/views.py:53`) but the frontend doesn't use it (see below).
- `memberportal/membermatters/constance_config.py:24`: `SITE_LOCALE_CURRENCY = "en-AU"` is sent to the frontend as `general.siteLocaleCurrency` (`api_general/views.py:131`). The backend never uses it.

### Phone numbers

- `memberportal/membermatters/constance_config.py:407`: `PROFILE_DEFAULT_PHONE_REGION = "AU"`.
- `memberportal/profile/phone.py:7`: `to_e164(raw, default_region)`.
- Used in `api_general/views.py:574,916` and `api_admin_tools/views.py:962`. Sent to the frontend as `features.signup.defaultPhoneRegion` (`api_general/views.py:82`).
- `memberportal/profile/management/commands/backfill_phone_e164.py`: a one-off command that takes its own `--region`.

### Location

- `memberportal/membermatters/constance_config.py:52`: `SITE_MAIL_ADDRESS`, used in email footers and in `/api/config` `contact.address` (`api_general/views.py:136`).
- `memberportal/membermatters/constance_config.py:237-242`: `SPACE_DIRECTORY_LOCATION_ADDRESS`, `SPACE_DIRECTORY_LOCATION_LAT`, `SPACE_DIRECTORY_LOCATION_LON`, published at `api_spacedirectory/views.py:113-117`.
- `memberportal/api_spacedirectory/models.py:45`: `SpaceAPISensor.location` is a free-text room or area name, not a geographic location.
- There's no country setting. The country is implied separately by the phone region, the currencies and the time zone.

### Background jobs

- `memberportal/membermatters/settings.py:449-452`: no `CELERY_TIMEZONE`. Celery therefore runs in UTC (`enable_utc` defaults to on), and new django-celery-beat crontab schedules default to UTC (`django_celery_beat.models.crontab_schedule_celery_timezone`). Any crontab task an admin creates fires on UTC unless they change that schedule's time zone. Interval schedules (e.g. `METRICS_INTERVAL`) aren't affected.

### Integrations

- `memberportal/api_member_tools/views.py:192-194`: the Vikunja task payload hard-codes `"week_start": 0`, `"timezone": ""` and `"language": "en"`.

## Frontend (Vue / Quasar)

### Language

- `src-frontend/src/boot/i18n.ts:8-9`: `locale: navigator.language`, `fallbackLocale: 'en-AU'`. The user can't change the language in the app, and the server's language settings aren't consulted.
- `src-frontend/src/i18n/index.ts`: registers `en-AU`, `en-NZ`, `en-US`, `en-GB`, `en-IE` and `sv-SE`. The four non-AU English folders are empty (`export default {};`) and exist only so `numberFormats` has a matching key.
- vue-i18n only falls back from specific to general (`sv-SE` → `sv`), not the other way. A browser that reports plain `sv` (Chrome does) or `sv-FI` gets English.
- `src-frontend/quasar.config.js:179`: `framework.lang: 'en-US'`. Quasar's built-in component strings (table pagination, date picker month names) are always US English, and Quasar writes this code to `<html lang>`. `src-frontend/index.html` sets no `lang` itself.

### Currency display

- `src-frontend/src/i18n/numberFormats.ts`: one `currency` format per locale key: `en-AU` → AUD, `en-NZ` → NZD, `en-US` → USD, `en-GB` → GBP, `en-IE` → EUR, `sv-SE` → SEK. The `SITE_LOCALE_CURRENCY` value picks both the currency **and** the number format.
- `src-frontend/src/store/modules/config.js:18`: `siteLocaleCurrency: 'en-AU'` until `/api/config` loads.
- `$n(value, 'currency', siteLocaleCurrency)` is used in:
  - `components/Billing/PlanCard.vue:14`, `TierCard.vue:15`, `SelectTier.vue:258,269,284`
  - `components/MemberBucks.vue:82,205-206`, `MemberBucksAddFunds.vue:34,41,47,153`, `MemberBucksDonateFunds.vue:147`
  - `components/AdminTools/DeviceDialog.vue:707`, `DevicesList.vue:284`
  - `components/AdminTools/ManageMember/MemberBillingTab.vue:71,390`, `MemberLogsTab.vue:289`, `MemberProfileTab.vue:330`
- `src-frontend/src/pages/AdminTools/PendingInvoices.vue:207-212`: a different approach. It uses `Intl.NumberFormat(undefined, …)` (the browser's locale) with the invoice's own currency, falling back to `'aud'`.
- `src-frontend/src/components/AdminTools/ManageTier.vue:169-178,390,599`: the plan currency is a free-text field defaulting to `'aud'`.
- `src-frontend/src/components/MemberBucksAddFunds.vue:34,41,47`: the top-up buttons hard-code 10, 20 and 30 instead of using `memberbucks_topup_options`.

### Time zone

- `src-frontend/src/mixins/formatMixin.ts:2-11`: loads the dayjs `utc` and `timezone` plugins and calls `dayjs.tz.guess()`, whose result is discarded (a no-op). All formatting uses `.local()`, i.e. the **browser's** time zone. The server's `TIME_ZONE` isn't sent to the frontend.
- `src-frontend/src/components/MeetingForm.vue:185-186`: meeting times are entered in the browser's time zone and sent as UTC ISO.

### Date formats

No dayjs locale is imported anywhere, so month names, `fromNow()` ("3 hours ago") and `humanize()` are always English, whatever the UI language.

Hard-coded format strings:

| File | Format | Output |
|---|---|---|
| `src/mixins/formatMixin.ts:25-26` `formatDate` | `D MMM YYYY, h:mm a` / `D MMM YYYY` | `27 Oct 2026, 2:00 pm` |
| `src/mixins/formatMixin.ts:30` `formatDay` | `D MMM YYYY` | `27 Oct 2026` |
| `src/mixins/formatMixin.ts:34-35` `formatDateSimple` | `DD/MM/YYYY, h:mm a` / **`D/MMM/YYYY`** | `27/10/2026, 2:00 pm` / `27/Oct/2026` (the date-only branch looks like a typo) |
| `src/store/modules/profile.js:77-78` | `D MMMM YYYY` | `27 October 2026` |
| `src/components/ProxyCard.vue:61` | **`Do MMMM YYYY`** | `27o October 2026`, a bug: `Do` needs dayjs's `advancedFormat` plugin, which isn't loaded |
| `src/components/stickers/Ticket.vue:81,84`, `ExtendedGreenTicket.vue:75-81`, `MemberStorageTag.vue:64` | `DD/MM/YY` | `27/10/26` |
| `src/components/stickers/VisitorTag.vue:74` | `DD/MM/YY hh:mm a` | `27/10/26 02:00 pm` |
| `src/components/MeetingForm.vue:51,66,86,176-177,233` | `YYYY-MM-DD HH:mm` (input mask) | `2026-10-27 14:00` |

Built-in browser formatting with three different locale choices for the same kind of data:

- `src/pages/MembershipPlan.vue:237-245`: `toLocaleString('en-au')`, hard-coded Australian.
- `src/components/MembershipStatusCard.vue:259,267`: `toLocaleDateString()`, the browser's locale.
- `src/pages/AdminTools/PendingInvoices.vue:214`: `toLocaleDateString()`, the browser's locale.

### Phone numbers

- `src/components/ProfileForm.vue:153`, `src/components/Account/RegistrationCard.vue:291`, `src/components/AdminTools/ManageMember/MemberProfileTab.vue:948`: `features.signup.defaultPhoneRegion || 'AU'`, a second hard-coded `AU` default.

## Deployment

- `docker/Dockerfile`: no `TZ`, `LANG` or `LC_ALL`, so the container runs in UTC with the POSIX locale. `gettext` is installed and `compilemessages` runs at build time.
- `docker/docker-compose.yml`, `docker/caprover.yaml`: neither sets `MM_TIME_ZONE` or `MM_LANGUAGE_CODE`, so new installs silently get `Australia/Brisbane` and `en-au`.
- `dev.env`: only `MM_ENV`.
- `.github/workflows/tests.backend.yml:71`: CI checks the Swedish catalog against the `.pot` file.

## Documentation

- `docs/POST_INSTALL_STEPS.md:66-88`, "Locale / Language Configuration":
  - The variable name is misspelled as `MM_LANGAUGE_CODE` (`:79`).
  - It says the time zone and language only affect "the server logs" (`:80`). In fact they also affect email dates, Django admin and parsing of offset-less client datetimes.
  - It gives the `sv-SE` currency format as `kr 12.50`. `Intl` actually renders `12,50 kr`.
  - There's a stray `.o` at the end of `:76`.
- `EMAIL_LANGUAGE` and `PROFILE_DEFAULT_PHONE_REGION` aren't documented in `POST_INSTALL_STEPS.md`. `MEMBERBUCKS_CURRENCY` is (`:189`). `EMAIL_LANGUAGE` is only described in `changes-summary-in-fork.md:57-62`.
- `src-frontend/src/i18n/README.md`: says to copy the `en-au` folder and add it to `i18n/index.js`. The folder is `en-AU` and the file is now `index.ts`. It doesn't mention `numberFormats.ts`.

## Inconsistencies worth fixing while streamlining

1. **Three unlinked currency settings.** What members are charged (`PaymentPlan.currency`, `MEMBERBUCKS_CURRENCY`) and what they're shown (`SITE_LOCALE_CURRENCY`) are independent. Plan prices are formatted with the display currency. `paymentPlans.intervalDescription` receives `plan.currency` but has no `{currency}` placeholder (`en-AU/index.ts:634`, `sv-SE/index.ts:621`). So a SEK plan on a site left at the `en-AU` default shows as `$100.00`. Meanwhile Pending Invoices shows the real invoice currency, and emails show `100.00 SEK`.
2. **Currency display is tied to a locale, not a currency.** `SITE_LOCALE_CURRENCY` picks both the ISO code and the separators and symbol placement. Supporting a new currency means editing `numberFormats.ts`, and the four empty English locales exist only for that.
3. **Four sources of language, none connected.** These are `MM_LANGUAGE_CODE` (server), `EMAIL_LANGUAGE` (member emails), `navigator.language` (UI) and the Quasar pack fixed at `en-US`, plus the hard-coded `'en-au'` in `MembershipPlan.vue`. A Swedish site can set emails to Swedish but can't make the UI default to Swedish for browsers that report `sv`.
4. **`MM_LANGUAGE_CODE` leaks into "English" emails.** The meeting proxy messages call `format_local_datetime()` before `send_single_email(..., language=ENGLISH)` applies its override. With no `LocaleMiddleware` the active language is `LANGUAGE_CODE`, so on an `sv` install those English emails carry a Swedish-formatted date.
5. **Time zone has four values that can disagree.** Server `TIME_ZONE` defaults to Brisbane, Celery and the container are UTC, and the UI uses the browser's zone. The server time zone isn't exposed to the frontend, so an admin travelling abroad, or a printed sticker, shows times in the device's zone, not the space's.
6. **Australian defaults scattered as literals.** `en-au`/`en-AU`, `Australia/Brisbane`, `aud` (backend model, constance, `ManageTier.vue` ×2, `PendingInvoices.vue`), `AU` (constance plus three frontend fallbacks), "in dollars" (`MEMBERBUCKS_MAX_TOPUP`), and `https://eventbrite.com.au` (`POST_INDUCTION_URL`, `constance_config.py:62`).
7. **Date formats ignore the UI language.** Format strings are hard-coded day-month-year with English month names. No dayjs locale is loaded, the same subscription date is formatted three different ways on three pages, and `ProxyCard.vue` prints `27o October 2026`.
8. **Two postal addresses and no country.** `SITE_MAIL_ADDRESS` and `SPACE_DIRECTORY_LOCATION_ADDRESS` usually hold the same address. Nothing records the country that the phone region, currency and time zone each assume.
9. **Code casing varies.** `en-au` (Django, `MembershipPlan.vue`), `en-AU` (constance, frontend), `sv-SE` (frontend, constance) versus the catalog directory `sv`. Django normalises these, but it makes grepping and comparing values error-prone.

## A possible consolidated shape

For discussion, not a decision:

- One **Localisation** fieldset in Constance (or an Admin Tools editor, matching the move away from Constance) holding:
  - `SITE_LANGUAGE`: the default UI language and member email language (replaces `EMAIL_LANGUAGE` and the hard-coded `fallbackLocale`).
  - `SITE_TIME_ZONE`: sent to the frontend so dates can be shown in the space's time zone. `MM_TIME_ZONE` would stay as the boot-time default.
  - `SITE_CURRENCY`: an ISO code used for memberbucks charges, as the default for new plans, and for display. It would replace `MEMBERBUCKS_CURRENCY` and `SITE_LOCALE_CURRENCY`. Formatting would follow the viewer's language with the currency passed explicitly, so `numberFormats.ts` and the empty English locales could go.
  - `SITE_COUNTRY`: drives the phone region default, replacing `PROFILE_DEFAULT_PHONE_REGION`.
  - Location (address, lat, lon) shared by the email footer and SpaceAPI.
- On the frontend, one date helper that takes the active i18n locale and the site time zone, loads the matching dayjs locale, and replaces the hard-coded `toLocale*` calls. It would also set the Quasar language pack from the active locale.
- Set `CELERY_TIMEZONE = TIME_ZONE` and pin `TIME_ZONE` in `settings_test.py`.
