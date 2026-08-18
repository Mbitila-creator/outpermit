from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ConferencesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "conferences"
    verbose_name = _("Conferences")

