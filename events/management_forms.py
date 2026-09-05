from django import forms

from core.models import Council, Country, Region
from permits.models import Department

from .access import is_system_event_administrator, user_department
from .models import Event, EventTimetable, Venue


class EventTimetableForm(forms.ModelForm):
    class Meta:
        model = EventTimetable
        fields = ("title_sw", "title_en", "pdf_file", "is_published")
        widgets = {
            "pdf_file": forms.ClearableFileInput(attrs={"accept": "application/pdf"}),
        }

    def clean_pdf_file(self):
        uploaded_file = self.cleaned_data.get("pdf_file")
        if uploaded_file and uploaded_file.size > 25 * 1024 * 1024:
            raise forms.ValidationError("The timetable PDF must not exceed 25 MB.")
        return uploaded_file


class LocationSelect(forms.Select):
    """Expose location relationships for client-side dependent selects."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        if value and getattr(value, "instance", None):
            instance = value.instance
            if isinstance(instance, Region):
                option["attrs"]["data-country"] = str(instance.country_id)
            elif isinstance(instance, Council):
                option["attrs"]["data-country"] = str(instance.region.country_id)
                option["attrs"]["data-region"] = str(instance.region_id)
        return option


class DepartmentEventForm(forms.ModelForm):
    venue_mode = forms.ChoiceField(
        label="Venue setup",
        choices=(("EXISTING", "Select a saved venue"), ("NEW", "Create a new venue")),
        initial="EXISTING",
        required=False,
        widget=forms.RadioSelect,
    )
    new_venue_name = forms.CharField(
        label="New venue name",
        max_length=200,
        required=False,
        help_text=(
            "Enter the venue name exactly as it should appear to participants."
        ),
        widget=forms.TextInput(attrs={
            "placeholder": "For example, Ministry Conference Hall",
            "autocomplete": "off",
        }),
    )
    new_venue_country = forms.ModelChoiceField(
        label="Country",
        queryset=Country.objects.none(),
        required=False,
        empty_label="Select country",
    )
    new_venue_region = forms.ModelChoiceField(
        label="Region",
        queryset=Region.objects.none(),
        required=False,
        empty_label="Select region",
        widget=LocationSelect,
    )
    new_venue_council = forms.ModelChoiceField(
        label="Council",
        queryset=Council.objects.none(),
        required=False,
        empty_label="Select council",
        help_text="The selected council automatically determines the venue's region and country.",
        widget=LocationSelect,
    )

    class Meta:
        model = Event
        fields = (
            "owning_department", "category", "venue_mode", "venue",
            "new_venue_name", "new_venue_country", "new_venue_region",
            "new_venue_council",
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
            "registration_opens_at": forms.DateTimeInput(attrs={"type": "datetime-local", "onchange": "this.blur()"}),
            "registration_closes_at": forms.DateTimeInput(attrs={"type": "datetime-local", "onchange": "this.blur()"}),
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local", "onchange": "this.blur()"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local", "onchange": "this.blur()"}),
            "description_sw": forms.Textarea(attrs={"rows": 3}),
            "description_en": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["venue"].label = "Choose an existing venue"
        self.fields["venue"].help_text = (
            "Select a saved venue, including its existing council and location."
        )
        self.fields["venue"].queryset = Venue.objects.filter(
            is_active=True
        ).select_related("council").order_by("name")
        self.fields["registration_closes_at"].help_text = (
            "Registration may remain open after the event starts, but it cannot "
            "close later than the event ending time. Leave empty to use the event end."
        )
        self.fields["new_venue_country"].queryset = Country.objects.filter(
            is_active=True
        ).order_by("name_en")
        self.fields["new_venue_region"].queryset = Region.objects.filter(
            is_active=True,
            country__is_active=True,
        ).select_related("country").order_by("name_en")
        self.fields["new_venue_council"].queryset = Council.objects.filter(
            is_active=True,
            region__is_active=True,
            region__country__is_active=True,
        ).select_related("region", "region__country").order_by(
            "region__name_en", "name_en"
        )
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
        venue_mode = cleaned_data.get("venue_mode") or "EXISTING"
        cleaned_data["venue_mode"] = venue_mode
        selected_venue = cleaned_data.get("venue")
        new_venue_name = " ".join(
            cleaned_data.get("new_venue_name", "").split()
        )
        cleaned_data["new_venue_name"] = new_venue_name
        country = cleaned_data.get("new_venue_country")
        region = cleaned_data.get("new_venue_region")
        council = cleaned_data.get("new_venue_council")
        if venue_mode == "NEW":
            if selected_venue:
                self.add_error("venue", "Clear the saved venue when creating a new one.")
            for field_name, value in (
                ("new_venue_name", new_venue_name),
                ("new_venue_country", country),
                ("new_venue_region", region),
                ("new_venue_council", council),
            ):
                if not value:
                    self.add_error(field_name, "This field is required for a new venue.")
            if country and region and region.country_id != country.pk:
                self.add_error("new_venue_region", "Select a region in the chosen country.")
            if region and council and council.region_id != region.pk:
                self.add_error("new_venue_council", "Select a council in the chosen region.")
        elif any((new_venue_name, country, region, council)):
            self.add_error(
                "venue_mode",
                "Choose ‘Create a new venue’ before entering new venue details.",
            )
        return cleaned_data

    def save(self, commit=True):
        event = super().save(commit=False)
        new_venue_name = self.cleaned_data.get("new_venue_name", "")
        if self.cleaned_data.get("venue_mode") == "NEW" and new_venue_name:
            council = self.cleaned_data["new_venue_council"]
            venue = Venue.objects.filter(
                name__iexact=new_venue_name,
                council=council,
                is_active=True,
            ).first()
            if venue is None:
                venue = Venue.objects.create(
                    name=new_venue_name,
                    council=council,
                    created_by=self.user,
                    updated_by=self.user,
                )
            event.venue = venue
        if commit:
            event.save()
            self.save_m2m()
        return event
