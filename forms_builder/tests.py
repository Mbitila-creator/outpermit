from types import SimpleNamespace

from django.test import SimpleTestCase

from .views import registration_identity_conflicts


class RegistrationIdentityConflictTests(SimpleTestCase):
    def setUp(self):
        self.existing = SimpleNamespace(
            submitter_email="Participant@Example.com",
            submitter_phone="+255 712 345 678",
        )

    def test_matching_email_blocks_registration_even_with_different_phone(self):
        duplicate, email_conflict, phone_conflict = (
            registration_identity_conflicts(
                [self.existing],
                " participant@example.com ",
                "0755000000",
            )
        )
        self.assertIs(duplicate, self.existing)
        self.assertTrue(email_conflict)
        self.assertFalse(phone_conflict)

    def test_matching_phone_blocks_registration_even_with_different_email(self):
        duplicate, email_conflict, phone_conflict = (
            registration_identity_conflicts(
                [self.existing],
                "different@example.com",
                "0712-345-678",
            )
        )
        self.assertIs(duplicate, self.existing)
        self.assertFalse(email_conflict)
        self.assertTrue(phone_conflict)

    def test_different_email_and_phone_are_allowed(self):
        duplicate, email_conflict, phone_conflict = (
            registration_identity_conflicts(
                [self.existing],
                "different@example.com",
                "0755000000",
            )
        )
        self.assertIsNone(duplicate)
        self.assertFalse(email_conflict)
        self.assertFalse(phone_conflict)
