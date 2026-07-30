from django import forms
from .models import SystemSetting, SecurityStage


class SystemSettingForm(forms.ModelForm):
    class Meta:
        model = SystemSetting
        fields = [
            'system_name',
            'organization_name',
            'organization_email',
            'organization_phone',
            'maintenance_mode',
            'allow_user_registration',

            # Open Task module customization
            'open_task_enabled',
            'allow_task_creation',
            'allow_task_assignment',
            'allow_task_progress_update',
            'allow_task_completion',
            'allow_task_export',

            # Open Permit module customization
            'open_permit_enabled',
            'allow_individual_permit',
            'allow_group_permit',
            'allow_permit_edit',
            'allow_permit_cancel',
            'allow_permit_export',
            'allow_permit_print',
            'allow_qr_code',
            'allow_badge_print',

            'backup_frequency',
            'security_level',
        ]

        widgets = {
            'system_name': forms.TextInput(attrs={'class': 'form-control'}),
            'organization_name': forms.TextInput(attrs={'class': 'form-control'}),
            'organization_email': forms.EmailInput(attrs={'class': 'form-control'}),
            'organization_phone': forms.TextInput(attrs={'class': 'form-control'}),

            'maintenance_mode': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_user_registration': forms.CheckboxInput(attrs={'class': 'form-check-input'}),

            'open_task_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_task_creation': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_task_assignment': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_task_progress_update': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_task_completion': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_task_export': forms.CheckboxInput(attrs={'class': 'form-check-input'}),

            'open_permit_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_individual_permit': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_group_permit': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_permit_edit': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_permit_cancel': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_permit_export': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_permit_print': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_qr_code': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_badge_print': forms.CheckboxInput(attrs={'class': 'form-check-input'}),

            'backup_frequency': forms.Select(attrs={'class': 'form-control'}),
            'security_level': forms.Select(attrs={'class': 'form-control'}),
        }


class SecurityStageForm(forms.ModelForm):
    class Meta:
        model = SecurityStage
        fields = [
            'name',
            'code',
            'description',
            'order',
            'is_active',
        ]

        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'order': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }