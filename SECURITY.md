# OutPermit production security

## Required deployment controls

Copy `production.env.example` into the hosting provider's protected environment
and replace every placeholder. Never commit the completed file. Generate the
Django secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Use HTTPS, set `DJANGO_DEBUG=false`, list only the real domains in
`DJANGO_ALLOWED_HOSTS`, and list their HTTPS origins in
`DJANGO_CSRF_TRUSTED_ORIGINS`. Rotate any secret that has previously appeared in
source control, chat, a screenshot, or logs.

The login throttle uses Django's cache. Set `DJANGO_CACHE_LOCATION` to a private
directory shared by the application's worker processes. For a multi-server
deployment, replace the file cache with a shared production cache such as Redis.

## Private uploads

Private documents are blocked under direct `/media/` URLs when requests pass
through Django. The production web server must apply the same rule: do not map
the whole media directory as public static content. Only public event assets
such as logos, banners and published timetables should be publicly served.
Private task, permit, finance, payment, questionnaire, meeting, conference-paper
and backup folders must be reachable only through authenticated Django download
views.

Uploads are restricted by size, approved filename extensions and common file
signatures. Production should additionally scan uploads with an antivirus or
malware-scanning service before long-term storage.

## Release checklist

Run these commands in the release environment:

```bash
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py test
python manage.py collectstatic --noinput
```

This release targets Python 3.10+, Django 5.2 LTS, `mysqlclient` 2.2.7, and
MySQL 8.0.11+ or MariaDB 10.5+. Do not upgrade the application dependency while
leaving the current XAMPP MariaDB 10.4 server in place.

Back up the database and uploaded media before migrations. Verify that anonymous
users cannot access administrative, report, task, finance, audit, or private
download URLs. Test each organizational role with both allowed and deliberately
forbidden records.

Do not store database dumps, SQLite databases, `.env` files, virtual
environments, collected static files, or uploaded media in Git. Removing a file
from the latest commit does not remove it from Git history; exposed secrets must
still be rotated, and sensitive history should be purged in a separately planned
maintenance operation.

## Reporting vulnerabilities

Report suspected vulnerabilities privately to the system owner. Include the
affected URL or module, the account role used, reproduction steps, and the
observed result. Do not include passwords, database dumps, identity documents,
or other personal data in the report.
