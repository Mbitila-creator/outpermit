from django import forms
from django.core.exceptions import ValidationError

from .models import (
    ConferencePaper,
    ConferencePaperReviewAssignment,
    ConferencePresentation,
    ConferencePaperCommunication,
    ConferenceProgrammeItem,
    ConferenceSession,
    ConferenceFeedback,
)


class ConferencePaperSubmissionForm(forms.ModelForm):
    confirmation = forms.BooleanField(
        label=(
            "I confirm that the information is correct and that all listed "
            "authors have agreed to this submission."
        ),
    )

    class Meta:
        model = ConferencePaper
        fields = (
            "submission_type",
            "presentation_format",
            "title",
            "abstract",
            "thematic_area",
            "keywords",
            "corresponding_author",
            "institution",
            "email",
            "phone",
            "co_authors",
            "document",
        )
        widgets = {
            "abstract": forms.Textarea(attrs={"rows": 9}),
            "co_authors": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {
            "abstract": "Provide a concise summary of the problem, methods, findings and contribution.",
            "keywords": "Separate keywords with commas.",
            "document": "Optional for an abstract; required for a full paper. PDF, DOC or DOCX, maximum 10 MB.",
        }

    def clean_abstract(self):
        abstract = self.cleaned_data["abstract"].strip()
        word_count = len(abstract.split())
        if word_count < 20:
            raise ValidationError("The abstract must contain at least 20 words.")
        if word_count > 1000:
            raise ValidationError("The abstract must not exceed 1,000 words.")
        return abstract


class ConferencePeerReviewForm(forms.ModelForm):
    SCORE_CHOICES = (("", "Select score"),) + tuple(
        (value, f"{value} — {label}")
        for value, label in (
            (1, "Very weak"), (2, "Weak"), (3, "Adequate"),
            (4, "Strong"), (5, "Excellent"),
        )
    )

    class Meta:
        model = ConferencePaperReviewAssignment
        fields = (
            "status", "conflict_reason", "relevance_score", "originality_score",
            "methodology_score", "clarity_score", "impact_score", "recommendation",
            "comments_to_author", "confidential_comments",
        )
        widgets = {
            "conflict_reason": forms.Textarea(attrs={"rows": 3}),
            "comments_to_author": forms.Textarea(attrs={"rows": 6}),
            "confidential_comments": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in (
            "relevance_score", "originality_score", "methodology_score",
            "clarity_score", "impact_score",
        ):
            self.fields[name].widget = forms.Select(choices=self.SCORE_CHOICES)
        self.fields["status"].choices = (
            (ConferencePaperReviewAssignment.Status.IN_PROGRESS, "Save as in progress"),
            (ConferencePaperReviewAssignment.Status.COMPLETED, "Submit completed review"),
            (ConferencePaperReviewAssignment.Status.CONFLICT, "Declare conflict of interest"),
        )


class ConferencePresentationScheduleForm(forms.ModelForm):
    class Meta:
        model = ConferencePresentation
        fields = (
            "session", "programme_item", "presenter_name", "starts_at", "ends_at",
            "venue_name", "status", "manager_notes",
        )
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "manager_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, event, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["session"].queryset = ConferenceSession.objects.filter(
            event=event, is_active=True,
        )
        self.fields["programme_item"].queryset = ConferenceProgrammeItem.objects.filter(
            session__event=event, is_active=True, is_published=True,
        )


class ConferencePresentationConfirmationForm(forms.ModelForm):
    confirmation = forms.BooleanField(
        label="I confirm that I will deliver this presentation at the scheduled time.",
    )

    class Meta:
        model = ConferencePresentation
        fields = ("presenter_name", "slides", "presenter_notes")
        widgets = {"presenter_notes": forms.Textarea(attrs={"rows": 4})}
        help_texts = {
            "slides": "Optional PDF, PPT or PPTX file, maximum 20 MB.",
        }


class ConferencePaperCommunicationForm(forms.ModelForm):
    class Meta:
        model = ConferencePaperCommunication
        fields = ("communication_type", "recipient_email", "subject", "message")
        widgets = {"message": forms.Textarea(attrs={"rows": 12})}


class ConferenceFeedbackForm(forms.ModelForm):
    is_anonymous = forms.BooleanField(
        label="Submit this evaluation anonymously",
        required=False,
        initial=True,
    )
    would_recommend = forms.TypedChoiceField(
        label="Would you recommend this conference to others?",
        choices=((True, "Yes"), (False, "No")),
        coerce=lambda value: value == "True",
        widget=forms.RadioSelect,
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = ConferenceFeedback
        fields = (
            "session", "is_anonymous", "respondent_name", "institution", "email",
            "overall_rating", "content_rating", "speakers_rating",
            "organization_rating", "venue_rating", "would_recommend",
            "most_valuable", "improvements", "additional_comments",
        )
        widgets = {
            "overall_rating": forms.RadioSelect,
            "content_rating": forms.RadioSelect,
            "speakers_rating": forms.RadioSelect,
            "organization_rating": forms.RadioSelect,
            "venue_rating": forms.RadioSelect,
            "most_valuable": forms.Textarea(attrs={"rows": 4}),
            "improvements": forms.Textarea(attrs={"rows": 4}),
            "additional_comments": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {
            "session": "Optional: select one session if this feedback concerns it specifically.",
        }

    def __init__(self, *args, event, **kwargs):
        super().__init__(*args, **kwargs)
        self.event = event
        self.fields["session"].queryset = ConferenceSession.objects.filter(
            event=event, is_active=True,
        ).order_by("starts_at", "display_order")
        self.fields["session"].empty_label = "Overall conference (all sessions)"
        self.fields["respondent_name"].required = False
        for field_name in (
            "overall_rating", "content_rating", "speakers_rating",
            "organization_rating", "venue_rating",
        ):
            self.fields[field_name].choices = tuple(
                (value, f"{value} — {label}")
                for value, label in (
                    (1, "Very poor"), (2, "Poor"), (3, "Good"),
                    (4, "Very good"), (5, "Excellent"),
                )
            )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("website"):
            raise ValidationError("Unable to submit this evaluation.")
        if cleaned_data.get("is_anonymous"):
            cleaned_data["respondent_name"] = ""
            cleaned_data["institution"] = ""
            cleaned_data["email"] = ""
        elif not (cleaned_data.get("respondent_name") or "").strip():
            self.add_error("respondent_name", "Enter your name or submit anonymously.")
        return cleaned_data

