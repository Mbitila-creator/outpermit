from django import forms
from forms_builder.models import FormSubmission

from .models import (
    LearningAssessment,
    LearningAssessmentResult,
    LearningAttendance,
    LearningEnrollment,
    LearningEventProfile,
    LearningFacilitator,
    LearningSession,
    SeminarQuestion,
    WorkshopActivity,
    WorkshopActivitySubmission,
)


class DateTimeLocalInput(forms.DateTimeInput):
    input_type = "datetime-local"


class LearningEventProfileForm(forms.ModelForm):
    class Meta:
        model = LearningEventProfile
        fields = (
            "learning_objectives", "target_audience",
            "minimum_attendance_percentage", "post_assessment_pass_percentage",
            "certificate_requires_manual_approval",
        )
        widgets = {
            "learning_objectives": forms.Textarea(attrs={"rows": 4}),
            "target_audience": forms.Textarea(attrs={"rows": 3}),
        }


class LearningFacilitatorForm(forms.ModelForm):
    class Meta:
        model = LearningFacilitator
        fields = (
            "full_name", "role", "position_title", "institution", "biography",
            "email", "phone", "display_order",
        )
        widgets = {"biography": forms.Textarea(attrs={"rows": 4})}


class LearningSessionForm(forms.ModelForm):
    class Meta:
        model = LearningSession
        fields = (
            "code", "title", "description", "session_type", "starts_at", "ends_at",
            "venue_name", "facilitators", "material", "is_published", "display_order",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "starts_at": DateTimeLocalInput(format="%Y-%m-%dT%H:%M"),
            "ends_at": DateTimeLocalInput(format="%Y-%m-%dT%H:%M"),
            "facilitators": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["facilitators"].queryset = profile.facilitators.filter(is_active=True)


class LearningEnrollmentForm(forms.ModelForm):
    class Meta:
        model = LearningEnrollment
        fields = ("registration", "full_name", "institution", "email", "phone", "status")

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["registration"].required = False
        self.fields["registration"].help_text = (
            "Link the approved registration when this participant may receive a certificate."
        )
        self.fields["registration"].queryset = FormSubmission.objects.filter(
            event_form__event=profile.event,
            is_active=True,
            is_complete=True,
        ).order_by("badge_name", "reference_number")


class LearningAssessmentForm(forms.ModelForm):
    class Meta:
        model = LearningAssessment
        fields = ("title", "assessment_type", "maximum_score", "is_published")


class LearningAssessmentResultForm(forms.ModelForm):
    class Meta:
        model = LearningAssessmentResult
        fields = ("assessment", "enrollment", "score")

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assessment"].queryset = profile.assessments.filter(is_active=True)
        self.fields["enrollment"].queryset = profile.enrollments.filter(is_active=True)


class LearningAttendanceForm(forms.ModelForm):
    class Meta:
        model = LearningAttendance
        fields = ("session", "enrollment")

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["session"].queryset = profile.sessions.filter(is_active=True)
        self.fields["enrollment"].queryset = profile.enrollments.filter(is_active=True)


class WorkshopActivityForm(forms.ModelForm):
    class Meta:
        model = WorkshopActivity
        fields = ("session", "title", "instructions", "due_at", "maximum_score")
        widgets = {
            "instructions": forms.Textarea(attrs={"rows": 4}),
            "due_at": DateTimeLocalInput(format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["session"].queryset = profile.sessions.filter(is_active=True)


class WorkshopActivitySubmissionForm(forms.ModelForm):
    class Meta:
        model = WorkshopActivitySubmission
        fields = ("activity", "enrollment", "response", "attachment", "score", "feedback")
        widgets = {
            "response": forms.Textarea(attrs={"rows": 4}),
            "feedback": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["activity"].queryset = WorkshopActivity.objects.filter(session__profile=profile, is_active=True)
        self.fields["enrollment"].queryset = profile.enrollments.filter(is_active=True)


class SeminarQuestionForm(forms.ModelForm):
    class Meta:
        model = SeminarQuestion
        fields = ("session", "participant_name", "question", "answer", "is_published")
        widgets = {
            "question": forms.Textarea(attrs={"rows": 4}),
            "answer": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["session"].queryset = profile.sessions.filter(is_active=True)
