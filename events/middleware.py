from django.core.exceptions import PermissionDenied

from .access import events_visible_to


class DepartmentEventAccessMiddleware:
    """Enforce department ownership for authenticated Event Management URLs."""

    protected_sections = ("/staff/", "/reports/", "/check-in/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not request.user.is_authenticated:
            return None
        path = request.path
        if "/event-management/" not in path or not any(
            section in path for section in self.protected_sections
        ):
            return None

        event = self._event_from_kwargs(view_kwargs)
        if event is not None and not events_visible_to(request.user).filter(
            pk=event.pk,
        ).exists():
            raise PermissionDenied
        return None

    @staticmethod
    def _event_from_kwargs(kwargs):
        from conferences.models import (
            ConferencePaper,
            ConferencePaperReviewAssignment,
            ConferenceSession,
        )
        from forms_builder.models import EventForm, FormSubmission
        from meetings.models import (
            Meeting,
            MeetingActionItem,
            MeetingActionProgressUpdate,
            MeetingDocument,
        )

        lookups = (
            ("form_id", "pk", EventForm, "event"),
            ("submission_id", "pk", FormSubmission, "event_form__event"),
            ("meeting_id", "pk", Meeting, "event"),
            ("action_id", "pk", MeetingActionItem, "meeting__event"),
            ("update_id", "pk", MeetingActionProgressUpdate, "action_item__meeting__event"),
            ("document_id", "pk", MeetingDocument, "meeting__event"),
            ("session_id", "pk", ConferenceSession, "event"),
            ("paper_id", "pk", ConferencePaper, "call__event"),
            (
                "assignment_id",
                "pk",
                ConferencePaperReviewAssignment,
                "paper__call__event",
            ),
            (
                "participant_token",
                "participant_token",
                FormSubmission,
                "event_form__event",
            ),
        )
        for argument, lookup_field, model, event_path in lookups:
            value = kwargs.get(argument)
            if value is None:
                continue
            row = model.objects.filter(**{lookup_field: value}).values_list(
                f"{event_path}_id",
                flat=True,
            ).first()
            if row is not None:
                from .models import Event

                return Event(pk=row)
        return None
