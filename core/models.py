from django.db import models


class SystemModule(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def save(self, *args, **kwargs):
        self.code = self.code.upper().strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name}"


# Event Management shares the platform audit and geographical records while
# retaining its original app labels for a safe migration path.
from .event_models import BaseModel, Council, Country, District, Region
