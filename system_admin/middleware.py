from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin

from .models import SystemSetting


class MaintenanceModeMiddleware(MiddlewareMixin):
    """
    Maintenance mode middleware.

    When maintenance mode is enabled:
    - Superusers can continue using the system.
    - Login and logout pages remain accessible.
    - Static and media files remain accessible.
    - Normal authenticated users see a maintenance page.
    - Anonymous users can still reach the login page.
    """

    def process_request(self, request):
        try:
            setting = SystemSetting.objects.first()

            if not setting or not setting.maintenance_mode:
                return None

            login_url = reverse("login")
            logout_url = reverse("logout")
            settings_url = reverse("system_admin:settings")

            allowed_paths = [
                login_url,
                logout_url,
                settings_url,
            ]

            if request.path.startswith("/static/"):
                return None

            if request.path.startswith("/media/"):
                return None

            if request.path.startswith("/admin/"):
                if request.user.is_authenticated and request.user.is_superuser:
                    return None

            if request.path in allowed_paths:
                return None

            if request.user.is_authenticated and request.user.is_superuser:
                return None

            if request.user.is_authenticated:
                return render(
                    request,
                    "system_admin/maintenance.html",
                    {
                        "system_name": setting.system_name,
                        "message": (
                            "The system is currently undergoing scheduled maintenance. "
                            "Please try again later or contact the System Administrator."
                        ),
                    },
                    status=503,
                )

            messages.warning(
                request,
                "The system is currently under maintenance. Please log in later."
            )
            return redirect(login_url)

        except Exception:
            return None