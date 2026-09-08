import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMessage
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from .email_backends import BrevoEmailBackend
from .database import database_config


class DatabaseConfigurationTests(SimpleTestCase):
    def test_sqlite_is_the_safe_default(self):
        config = database_config({}, Path("/tmp/outpermit"))

        self.assertEqual(config["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(config["NAME"], Path("/tmp/outpermit/db.sqlite3"))

    def test_mysql_uses_explicit_environment_values(self):
        config = database_config(
            {
                "DB_ENGINE": "mysql",
                "DB_NAME": "outpermit_mysql",
                "DB_USER": "outpermit_user",
                "DB_PASSWORD": "local-secret",
                "DB_HOST": "127.0.0.1",
                "DB_PORT": "3306",
            },
            Path("/tmp/outpermit"),
        )

        self.assertEqual(config["ENGINE"], "django.db.backends.mysql")
        self.assertEqual(config["NAME"], "outpermit_mysql")
        self.assertEqual(config["USER"], "outpermit_user")
        self.assertEqual(config["OPTIONS"]["charset"], "utf8mb4")

    def test_mysql_rejects_missing_credentials(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured,
            "DB_NAME, DB_USER, DB_PASSWORD",
        ):
            database_config(
                {"DB_ENGINE": "mysql"},
                Path("/tmp/outpermit"),
            )


@override_settings(
    BREVO_API_KEY="test-api-key",
    BREVO_API_URL="https://api.brevo.test/v3/smtp/email",
    BREVO_TIMEOUT=10,
    EVENT_EMAIL_SENDER_NAME="MoEST-Event Management System",
    EVENT_EMAIL_REPLY_TO="noreply@example.org",
    EVENT_EMAIL_NO_REPLY_NOTICE="Please do not reply to this email.",
)
class BrevoEmailBackendTests(SimpleTestCase):
    @patch("config.email_backends.urlopen")
    def test_sends_message_using_brevo_api(self, mocked_urlopen):
        response = MagicMock(status=201)
        response.__enter__.return_value = response
        mocked_urlopen.return_value = response
        message = EmailMessage(
            subject="Registration received",
            body="Your participant portal is available.",
            from_email="Events Team <events@example.org>",
            to=["Participant <participant@example.org>"],
        )

        delivered = BrevoEmailBackend().send_messages([message])

        self.assertEqual(delivered, 1)
        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["sender"]["email"], "events@example.org")
        self.assertEqual(
            payload["sender"]["name"],
            "MoEST-Event Management System",
        )
        self.assertEqual(payload["replyTo"]["email"], "noreply@example.org")
        self.assertIn(
            "Please do not reply to this email.",
            payload["textContent"],
        )
        self.assertEqual(payload["to"][0]["email"], "participant@example.org")
        self.assertEqual(request.headers["Api-key"], "test-api-key")

    @override_settings(BREVO_API_KEY="")
    def test_missing_api_key_raises_clear_error(self):
        message = EmailMessage(
            subject="Test",
            body="Test",
            from_email="events@example.org",
            to=["participant@example.org"],
        )
        with self.assertRaisesMessage(RuntimeError, "BREVO_API_KEY"):
            BrevoEmailBackend().send_messages([message])


class IntegratedEventUrlTests(SimpleTestCase):
    def test_submission_success_has_canonical_integrated_url(self):
        self.assertEqual(
            reverse(
                "forms_builder:submission_success",
                kwargs={"reference_number": "NESIF-2026-REG-00093"},
            ),
            "/event-management/submissions/NESIF-2026-REG-00093/success/",
        )

    def test_old_language_prefixed_success_url_redirects(self):
        response = self.client.get(
            "/en/submissions/NESIF-2026-REG-00093/success/"
        )
        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response.url,
            "/event-management/submissions/NESIF-2026-REG-00093/success/",
        )
