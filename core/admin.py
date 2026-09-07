from django.contrib import admin
from .models import Notification, SystemModule

admin.site.register(SystemModule)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("event_key", "channel", "recipient", "status", "attempts", "created_at")
    list_filter = ("channel", "status", "event_key")
    search_fields = ("recipient", "subject", "message")
    readonly_fields = ("attempts", "last_error", "sent_at", "created_at", "updated_at")
