"""Backward-compatible URLs for Event Management links issued before integration."""

from django.urls import path
from django.views.generic import RedirectView


def legacy_redirect(pattern_name):
    return RedirectView.as_view(
        pattern_name=pattern_name,
        permanent=True,
        query_string=True,
    )


urlpatterns = [
    path(
        "check-in/<uuid:participant_token>/",
        legacy_redirect("checkin:participant"),
    ),
    path(
        "participants/<uuid:participant_token>/",
        legacy_redirect("forms_builder:participant_portal"),
    ),
    path(
        "participants/<uuid:participant_token>/badge/",
        legacy_redirect("forms_builder:participant_badge"),
    ),
    path(
        "participants/<uuid:participant_token>/certificate/",
        legacy_redirect("forms_builder:participant_certificate"),
    ),
    path(
        "participants/<uuid:participant_token>/payment/",
        legacy_redirect("forms_builder:participant_payment"),
    ),
    path(
        "participants/<uuid:participant_token>/payment/receipt/",
        legacy_redirect("forms_builder:payment_receipt"),
    ),
    path(
        "participants/<uuid:participant_token>/discussion-questions/",
        legacy_redirect("conferences:participant_guiding_questions"),
    ),
    path(
        "participants/<uuid:participant_token>/discussion-questions/<int:session_id>/",
        legacy_redirect("conferences:participant_session_guiding_questions"),
    ),
    path(
        "certificates/verify/<uuid:participant_token>/",
        legacy_redirect("forms_builder:certificate_verification"),
    ),
    path(
        "payments/<uuid:participant_token>/<int:payment_id>/verify/",
        legacy_redirect("forms_builder:payment_receipt_verification"),
    ),
    path(
        "booths/<uuid:public_token>/",
        legacy_redirect("forms_builder:booth_detail"),
    ),
    path(
        "special-events/participants/<uuid:token>/",
        legacy_redirect("events:special_event_participant_verify"),
    ),
    path(
        "conference-certificates/<uuid:verification_token>/verify/",
        legacy_redirect("conferences:certificate_verify"),
    ),
    path(
        "conference-papers/<uuid:public_token>/",
        legacy_redirect("conferences:paper_status"),
    ),
    path(
        "events/<slug:event_slug>/forms/<slug:form_slug>/",
        legacy_redirect("forms_builder:public_event_form"),
    ),
    path(
        "conferences/<slug:event_slug>/programme/",
        legacy_redirect("conferences:public_programme"),
    ),
]
