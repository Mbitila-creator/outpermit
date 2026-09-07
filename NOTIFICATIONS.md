# Notification deployment configuration

Notifications are stored in `core.Notification` before delivery. Email uses
Django's configured email backend. SMS uses a pluggable class with a
`send(recipient, message, sender=None)` method.

## Environment variables

```text
NOTIFICATION_CHANNELS=EMAIL
NOTIFICATION_MAX_ATTEMPTS=3
EMAIL_BACKEND=config.email_backends.BrevoEmailBackend
DEFAULT_FROM_EMAIL=MoEST <verified@example.go.tz>
BREVO_API_KEY=replace-at-deployment
PUBLIC_BASE_URL=https://example.go.tz
SMS_BACKEND=core.sms_backends.DisabledSMSBackend
SMS_FROM=
```

Until an SMS provider is selected, leave SMS out of `NOTIFICATION_CHANNELS`.
For local inspection, `core.sms_backends.ConsoleSMSBackend` is available.

Run this command from a scheduler to retry failed/pending deliveries:

```bash
python manage.py process_notifications
```

Event reminders additionally require:

```bash
python manage.py send_due_reminders
```

Never commit provider passwords, API keys, or production sender credentials.
