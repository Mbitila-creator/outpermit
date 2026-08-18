from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import Event


def special_event_queryset():
    return Event.objects.select_related("category").filter(
        is_active=True,
    ).filter(
        Q(category__code__iexact="SPECIAL_EVENT")
        | Q(category__code__iexact="SPECIAL EVENT")
        | Q(category__code__iexact="SPECIAL-EVENT")
        | Q(category__slug="special-event")
        | Q(category__name_en__iexact="Special Event")
    ).order_by("-starts_at", "code")


class SpecialEventParticipantImportForm(forms.Form):
    event = forms.ModelChoiceField(
        label="Special event",
        queryset=Event.objects.none(),
        empty_label="Select a special event",
    )
    workbook = forms.FileField(
        label="Researcher Excel file",
        help_text="Upload a complete .xlsx file containing researchers and publications.",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = special_event_queryset()
        if user is not None:
            from .access import events_visible_to

            queryset = queryset.filter(pk__in=events_visible_to(user))
        self.fields["event"].queryset = queryset

    def clean_event(self):
        event = self.cleaned_data["event"]
        if not event.category.is_special_event:
            raise ValidationError(
                "Select an event in the Special Event category."
            )
        return event

    def clean_workbook(self):
        workbook = self.cleaned_data["workbook"]
        if not workbook.name.lower().endswith(".xlsx"):
            raise ValidationError("Upload a valid .xlsx Excel file.")
        if workbook.size > 5 * 1024 * 1024:
            raise ValidationError("The Excel file must not exceed 5 MB.")
        return workbook
