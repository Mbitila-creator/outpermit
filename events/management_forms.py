from django import forms

from permits.models import Department

from .access import is_system_event_administrator, user_department
from .models import Event


class DepartmentEventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = (
            "owning_department", "category", "venue", "code", "title_sw",
            "title_en", "description_sw", "description_en",
            "organizer_name_sw", "organizer_name_en", "contact_person",
            "contact_email", "contact_phone", "registration_opens_at",
            "registration_closes_at", "starts_at", "ends_at",
            "maximum_participants", "status", "is_public",
            "registration_enabled", "evaluation_enabled", "qr_checkin_enabled",
            "badge_enabled", "certificate_enabled", "booth_enabled",
            "payment_enabled", "participation_fee", "payment_currency",
        )
        widgets = {
            "registration_opens_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "registration_closes_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "description_sw": forms.Textarea(attrs={"rows": 3}),
            "description_en": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if is_system_event_administrator(user):
            self.fields["owning_department"].queryset = Department.objects.filter(
                is_active=True
            ).order_by("code")
        else:
            department = user_department(user)
            self.fields["owning_department"].queryset = Department.objects.filter(
                pk=getattr(department, "pk", None)
            )
            self.fields["owning_department"].initial = department
            self.fields["owning_department"].disabled = True

    def clean_owning_department(self):
        if is_system_event_administrator(self.user):
            return self.cleaned_data["owning_department"]
        department = user_department(self.user)
        if not department:
            raise forms.ValidationError("Your account must be assigned to a department.")
        return department
