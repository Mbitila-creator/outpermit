import os
import shutil
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect

from .models import SystemSetting, SecurityStage, BackupRecord
from .forms import SystemSettingForm, SecurityStageForm


def is_system_admin(user):
    return user.is_authenticated and user.is_superuser


@login_required
@user_passes_test(is_system_admin)
def system_settings(request):
    setting, created = SystemSetting.objects.get_or_create(id=1)

    if request.method == 'POST':
        form = SystemSettingForm(request.POST, instance=setting)
        if form.is_valid():
            form.save()
            messages.success(request, 'System settings updated successfully.')
            return redirect('system_admin:settings')
    else:
        form = SystemSettingForm(instance=setting)

    return render(request, 'system_admin/settings.html', {
        'form': form,
        'setting': setting,
    })


@login_required
@user_passes_test(is_system_admin)
def security_stages(request):
    stages = SecurityStage.objects.all().order_by('order')

    if request.method == 'POST':
        form = SecurityStageForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Security stage added successfully.')
            return redirect('system_admin:security_stages')
    else:
        form = SecurityStageForm()

    return render(request, 'system_admin/security_stages.html', {
        'stages': stages,
        'form': form,
    })


@login_required
@user_passes_test(is_system_admin)
def backup_list(request):
    backups = BackupRecord.objects.all().order_by('-created_at')

    return render(request, 'system_admin/backups.html', {
        'backups': backups,
    })


@login_required
@user_passes_test(is_system_admin)
def create_backup(request):
    try:
        backup_dir = os.path.join(settings.MEDIA_ROOT, 'system_backups')
        os.makedirs(backup_dir, exist_ok=True)

        db_path = settings.DATABASES['default']['NAME']

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f'outpermit_backup_{timestamp}.sqlite3'
        backup_path = os.path.join(backup_dir, backup_name)

        shutil.copy2(db_path, backup_path)

        BackupRecord.objects.create(
            backup_name=backup_name,
            backup_file=f'system_backups/{backup_name}',
            status='SUCCESS',
            created_by=request.user
        )

        messages.success(request, 'System backup created successfully.')

    except Exception as e:
        BackupRecord.objects.create(
            backup_name='Failed Backup',
            status='FAILED',
            remarks=str(e),
            created_by=request.user
        )

        messages.error(request, f'Backup failed: {e}')

    return redirect('system_admin:backup_list')