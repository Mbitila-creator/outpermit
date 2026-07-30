from django.contrib import admin
from .models import SummitEvent, SummitParticipant


@admin.register(SummitEvent)
class SummitEventAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'name',
        'venue',
        'start_date',
        'end_date',
        'is_open',
        'is_archived',
    )
    search_fields = ('code', 'name', 'venue')
    list_filter = ('is_open', 'is_archived', 'start_date')


@admin.register(SummitParticipant)
class SummitParticipantAdmin(admin.ModelAdmin):
    list_display = (
        'registration_number',
        'full_name',
        'event',
        'institution',
        'phone',
        'email',
        'region',
        'attendance_type',
        'checked_in',
    )
    search_fields = (
        'registration_number',
        'full_name',
        'institution',
        'phone',
        'email',
    )
    list_filter = ('event', 'attendance_type', 'checked_in', 'region')
