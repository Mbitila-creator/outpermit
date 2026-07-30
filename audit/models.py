from django.db import models
from django.contrib.auth.models import User


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("CREATE", "Create"),
        ("UPDATE", "Update"),
        ("DELETE", "Delete"),
        ("SUBMIT", "Submit"),
        ("APPROVE", "Approve"),
        ("RETURN", "Return"),
        ("REJECT", "Reject"),
        ("CLOSE", "Close"),
        ("LOGIN", "Login"),
        ("LOGOUT", "Logout"),
        ("SYSTEM", "System"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs"
    )

    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    module = models.CharField(max_length=50)
    reference_no = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True)
    browser = models.CharField(max_length=200, blank=True)
    request_url = models.CharField(max_length=500, blank=True)
    http_method = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at} - {self.module} - {self.action}"