from django.db import models
from django.contrib.auth.models import User


class SecurityStage(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    order = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.name


class BackupRecord(models.Model):
    BACKUP_STATUS = [
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
    ]

    backup_name = models.CharField(max_length=255)
    backup_file = models.FileField(upload_to='system_backups/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=BACKUP_STATUS, default='SUCCESS')
    remarks = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.backup_name


class SystemSetting(models.Model):
    BACKUP_FREQUENCY = [
        ('MANUAL', 'Manual Only'),
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
    ]

    SECURITY_LEVEL = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
    ]

    system_name = models.CharField(
        max_length=255,
        default='Outpermit Management System'
    )
    organization_name = models.CharField(max_length=255, blank=True, null=True)
    organization_email = models.EmailField(blank=True, null=True)
    organization_phone = models.CharField(max_length=50, blank=True, null=True)

    maintenance_mode = models.BooleanField(default=False)
    allow_user_registration = models.BooleanField(default=False)

    # Open Task module customization
    open_task_enabled = models.BooleanField(default=True)
    allow_task_creation = models.BooleanField(default=True)
    allow_task_assignment = models.BooleanField(default=True)
    allow_task_progress_update = models.BooleanField(default=True)
    allow_task_completion = models.BooleanField(default=True)
    allow_task_export = models.BooleanField(default=True)

 # Open Permit module customization
    open_permit_enabled = models.BooleanField(default=True)
    allow_individual_permit = models.BooleanField(default=True)
    allow_group_permit = models.BooleanField(default=True)
    allow_permit_edit = models.BooleanField(default=True)
    allow_permit_cancel = models.BooleanField(default=True)
    allow_permit_export = models.BooleanField(default=True)
    allow_permit_print = models.BooleanField(default=True)
    allow_qr_code = models.BooleanField(default=True)
    allow_badge_print = models.BooleanField(default=True)

    backup_frequency = models.CharField(
        max_length=50,
        choices=BACKUP_FREQUENCY,
        default='MANUAL'
    )

    security_level = models.CharField(
        max_length=50,
        choices=SECURITY_LEVEL,
        default='MEDIUM'
    )

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.system_name