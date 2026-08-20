from django import forms

from permits.models import Department

from .access import is_system_event_administrator, user_department
from .models import Event, Venue


class DepartmentEventForm(forms.ModelForm):
    new_venue_name = forms.CharField(
        label="Or enter a new venue",
        max_length=200,
        required=False,
        help_text=(
            "Type a venue name only when it is not available in the list above. "
            "It will be saved for future events."
        ),
        widget=forms.TextInput(attrs={
            "placeholder": "For example, Ministry Conference Hall",
            "autocomplete": "off",
        }),
    )

    class Meta:
        model = Event
        fields = (
            "owning_department", "category", "venue", "new_venue_name",
            "code", "title_sw",
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
        self.fields["venue"].label = "Choose an existing venue"
        self.fields["venue"].help_text = (
            "Select a saved venue, or leave this empty and type a new venue below."
        )
        self.fields["venue"].queryset = Venue.objects.filter(
            is_active=True
        ).select_related("council").order_by("name")
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

    def clean(self):
        cleaned_data = super().clean()
        selected_venue = cleaned_data.get("venue")
        new_venue_name = " ".join(
            cleaned_data.get("new_venue_name", "").split()
        )
        cleaned_data["new_venue_name"] = new_venue_name
        if selected_venue and new_venue_name:
            self.add_error(
                "new_venue_name",
                "Choose an existing venue or enter a new venue, not both.",
            )
        return cleaned_data

    def save(self, commit=True):
        event = super().save(commit=False)
        new_venue_name = self.cleaned_data.get("new_venue_name", "")
        if new_venue_name:
            venue = Venue.objects.filter(
                name__iexact=new_venue_name,
                council__isnull=True,
                is_active=True,
            ).first()
            if venue is None:
                venue = Venue.objects.create(
                    name=new_venue_name,
                    created_by=self.user,
                    updated_by=self.user,
                )
            event.venue = venue
        if commit:
            event.save()
            self.save_m2m()
        return event
