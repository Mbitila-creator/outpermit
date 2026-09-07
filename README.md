# OutPermit Management System

OutPermit is a Django-based Ministry Enterprise Management Platform for the
Ministry of Education, Science and Technology (MoEST). It combines staff
permission processing, task management, finance workflows, departmental event
management, questionnaires, attendance, certificates, reporting and audit
functions in one role-aware system.

## Main capabilities

- **Permission Management** — create, review, approve, return, reject and close
  external-work permit requests through the organizational hierarchy.
- **Task Management** — create individual and group tasks, nominate a team
  leader, propose tasks for approval, request staff from another department and
  monitor performance.
- **Finance Management** — manage minute sheets, finance requests, budgets,
  payments, retirement and departmental financial reports.
- **Event Management** — manage exhibitions, meetings, seminars, workshops,
  conferences, training and special events by department.
- **Questionnaire Builder** — create bilingual forms with conditional logic,
  calculations, repeating sections, dynamic labels, choice filtering, imports,
  QR codes and printable forms.
- **Registration and Attendance** — register participants, approve
  registrations, issue badges, check participants in and track attendance.
- **Certificates** — authorize, generate, download and verify QR-protected
  certificates.
- **Reporting and Analytics** — produce departmental and executive reports,
  questionnaire statistics, charts, Excel exports and PDF reports.
- **Administration and Audit** — manage users, organizational structures,
  roles, workflows, backups and activity logs.
- **Notifications** — database-backed email/SMS-ready notification delivery,
  retries and administrative delivery monitoring.

## Technology

- Python and Django 4.2
- SQLite by default
- ReportLab and pypdf for PDF processing
- openpyxl for spreadsheet import/export
- Pillow and qrcode for images and QR codes
- python-docx for Word documents

See `requirements.txt` for the complete dependency list.

## Project applications

| Application | Responsibility |
|---|---|
| `permits` | Users, organization, permit requests and approvals |
| `tasks` | Tasks, assignments, proposals and cross-department requests |
| `finance` | Finance workflows, budgets, payments and reports |
| `events` | Departmental events and access control |
| `forms_builder` | Questionnaires, submissions, payments and notifications |
| `checkin` | Participant attendance and check-in |
| `meetings` | Meeting invitations, RSVP, minutes and actions |
| `conferences` | Conference papers, programmes and communications |
| `learning_events` | Training and other learning-event workflows |
| `system_admin` | Platform administration and maintenance |
| `audit` | Audit records and activity reporting |
| `workflow` | Shared workflow configuration |
| `core` | Shared records, services and notification infrastructure |

## Local installation

### 1. Clone the repository

```bash
git clone https://github.com/Mbitila-creator/outpermit.git
cd outpermit
```

### 2. Create and activate a virtual environment

macOS or Linux:

```bash
python3 -m venv venv
source venv/bin/activate
```

Windows:

```powershell
py -m venv venv
venv\Scripts\activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Prepare the local database

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. Start the development server

```bash
python manage.py runserver
```

Open <http://127.0.0.1:8000/>. Django Admin is available at
<http://127.0.0.1:8000/admin/>.

## Common development commands

```bash
# Validate project configuration
python manage.py check

# Check whether model changes need migrations
python manage.py makemigrations --check --dry-run

# Run all automated tests
python manage.py test

# Gather production static files
python manage.py collectstatic --noinput
```

Never commit the local `db.sqlite3`, virtual environment, provider credentials,
uploaded media or generated static files.

## Roles and organizational access

Access is determined by the user's primary organizational role and optional
module-specific roles. The platform supports Requesters, Heads of Unit,
Assistant Directors, Directors, the Commissioner of Education, Deputy
Permanent Secretaries, the Permanent Secretary and System Administrators.

Department, division, unit and section assignments determine which records,
staff, events, reports and approval actions a user can access. Do not bypass
these assignments by granting broad Django permissions unless the account is a
genuine system administrator.

## Notifications

Notification records are stored before delivery. Email uses Django's configured
email backend. SMS is provider-neutral and remains disabled until an adapter and
credentials are configured.

Full configuration and scheduler instructions are documented in
[`NOTIFICATIONS.md`](NOTIFICATIONS.md).

Useful commands:

```bash
python manage.py process_notifications
python manage.py send_due_reminders
```

Provider API keys, SMTP passwords and sender credentials must be supplied using
the hosting environment and must never be committed to Git.

## PythonAnywhere deployment

The production application is currently hosted under the PythonAnywhere user
`Mbitila`. After tested changes have been committed and pushed to `main`, open a
PythonAnywhere Bash console and run:

```bash
cd ~/outpermit
git pull --ff-only origin main
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check
touch /var/www/Mbitila_pythonanywhere_com_wsgi.py
```

Run `migrate` when a deployment contains migrations. Run `collectstatic` when
static assets changed. Creating a database backup before production migrations
is strongly recommended.

Example SQLite backup:

```bash
mkdir -p ~/outpermit-backups
cp -p ~/outpermit/db.sqlite3 \
  ~/outpermit-backups/db-$(date +%Y%m%d-%H%M%S).sqlite3
```

## Git workflow

Inspect changes before committing:

```bash
git status
git diff --check
git diff
```

Commit only intended source files, then synchronize safely:

```bash
git add <changed-files>
git commit -m "Describe the completed change"
git pull --rebase origin main
git push origin main
```

Do not use force-push on `main`. Do not add `db.sqlite3` or `venv/` to a feature
commit.

## Production checklist

Before moving to a final production provider:

1. Use environment-specific secret and security settings.
2. Disable Django debug mode.
3. Restrict allowed hosts and configure HTTPS securely.
4. Use a managed production database and tested backups.
5. Configure a verified email sender and delivery domain.
6. Select and configure an SMS provider only after contractual approval.
7. Schedule notification retries and event reminders.
8. Configure logging, monitoring and error alerts.
9. Run migrations, system checks and the complete test suite.
10. Test every approval role using non-production test accounts.

## Data safety

Local and production databases are separate. Running migrations on a developer
computer affects only that computer's configured database. Production
migrations must be executed explicitly on the production host.

Preserve uploaded event records and production data during upgrades. Existing
modules should be extended through migrations and focused changes rather than
being rebuilt or replaced unnecessarily.

## License and ownership

This repository contains an internal MoEST management system. Distribution,
deployment and access should follow the Ministry's authorization, information
security and data-protection requirements.
