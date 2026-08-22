import json
from email.utils import parseaddr
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import sanitize_address


class BrevoEmailBackend(BaseEmailBackend):
    """Send Django email messages through Brevo's HTTPS API."""

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        api_key = settings.BREVO_API_KEY.strip()
        if not api_key:
            if self.fail_silently:
                return 0
            raise RuntimeError("BREVO_API_KEY is not configured.")

        sent_count = 0
        for message in email_messages:
            try:
                self._send_message(message, api_key)
                sent_count += 1
            except Exception:
                if not self.fail_silently:
                    raise
        return sent_count

    def _send_message(self, message, api_key):
        sender_name, sender_email = parseaddr(message.from_email)
        if not sender_email:
            raise ValueError("The email message does not have a valid sender.")
        sender_name = settings.EVENT_EMAIL_SENDER_NAME or sender_name
        recipients = [
            self._address_payload(address)
            for address in message.to
            if parseaddr(address)[1]
        ]
        if not recipients:
            return
        payload = {
            "sender": {
                "email": sender_email,
                **({"name": sender_name} if sender_name else {}),
            },
            "to": recipients,
            "subject": message.subject,
            "textContent": self._text_content(message),
        }
        html_content = self._html_content(message)
        if html_content:
            payload["htmlContent"] = html_content
        reply_address = (
            settings.EVENT_EMAIL_REPLY_TO
            or (message.reply_to[0] if message.reply_to else sender_email)
        )
        if reply_address:
            reply_name, reply_email = parseaddr(reply_address)
            if reply_email:
                payload["replyTo"] = {
                    "email": reply_email,
                    **({"name": reply_name} if reply_name else {}),
                }
        request = Request(
            settings.BREVO_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "accept": "application/json",
                "api-key": api_key,
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=settings.BREVO_TIMEOUT) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(
                        f"Brevo returned unexpected status {response.status}."
                    )
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(
                f"Brevo rejected the email ({error.code}): {details}"
            ) from error
        except URLError as error:
            raise RuntimeError(
                f"Brevo could not be reached: {error.reason}"
            ) from error

    @staticmethod
    def _address_payload(address):
        name, email = parseaddr(sanitize_address(address, "utf-8"))
        return {"email": email, **({"name": name} if name else {})}

    @staticmethod
    def _text_content(message):
        body = str(message.body or "").rstrip()
        notice = settings.EVENT_EMAIL_NO_REPLY_NOTICE
        if notice and notice not in body:
            return f"{body}\n\n---\n{notice}" if body else notice
        return body

    @staticmethod
    def _html_content(message):
        for alternative in getattr(message, "alternatives", []):
            if alternative.mimetype == "text/html":
                return alternative.content
        return ""
