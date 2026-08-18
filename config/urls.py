from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include


urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/", admin.site.urls),

    # Permits module
    path("", include("permits.urls")),

    # Tasks module
    path("tasks/", include("tasks.urls")),

    # Finance module
    path("finance/", include("finance.urls")),

    # System admin module
    path("system-admin/", include("system_admin.urls")),

    # Department-scoped Event Management module.
    path("event-management/", include("events.urls")),
    path("event-management/", include("forms_builder.urls")),
    path("event-management/", include("checkin.urls")),
    path("event-management/", include("meetings.urls")),
    path("event-management/", include("conferences.urls")),

    path("audit/", include("audit.urls")),

    path("workflow/", include("workflow.urls")),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
