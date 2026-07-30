from django.contrib import admin
from .models import SecurityStage, BackupRecord, SystemSetting


@admin.register(SecurityStage)
class SecurityStageAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'order', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'code')


@admin.register(BackupRecord)
class BackupRecordAdmin(admin.ModelAdmin):
    list_display = ('backup_name', 'status', 'created_by', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('backup_name',)
    readonly_fields = ('created_at',)


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = (
        'system_name',
        'organization_name',
        'backup_frequency',
        'security_level',
        'maintenance_mode',
        'updated_at',
    )