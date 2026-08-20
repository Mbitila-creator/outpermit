from django.urls import path

from . import views
from .department_views import (
    department_event_create,
    department_event_detail,
    department_event_list,
)


app_name = "events"

urlpatterns = [
    path(
        "",
        department_event_list,
        name="department_event_list",
    ),
    path(
        "public/",
        views.home,
        name="home",
    ),
    path("new/", department_event_create, name="department_event_create"),
    path(
        "manage/<slug:event_slug>/",
        department_event_detail,
        name="department_event_detail",
    ),
    path(
        "events/<slug:event_slug>/",
        views.event_detail,
        name="event_detail",
    ),
    path(
        "staff/special-events/participants/",
        views.special_event_participant_list,
        name="special_event_participant_list",
    ),
    path(
        "staff/special-events/participants/import/",
        views.special_event_participant_import,
        name="special_event_participant_import",
    ),
    path(
        "staff/special-events/participants/print/",
        views.special_event_participant_print,
        name="special_event_participant_print",
    ),
    path(
        "staff/special-events/participants/cards.zip",
        views.special_event_participant_cards_zip,
        name="special_event_participant_cards_zip",
    ),
    path(
        "staff/special-events/participants/cards.docx",
        views.special_event_participant_cards_word,
        name="special_event_participant_cards_word",
    ),
    path(
        "special-events/participants/<uuid:token>/",
        views.special_event_participant_verify,
        name="special_event_participant_verify",
    ),
    path(
        "special-events/participants/<uuid:token>/qr.png",
        views.special_event_participant_qr,
        name="special_event_participant_qr",
    ),
    path(
        "special-events/participants/<uuid:token>/card.png",
        views.special_event_participant_card_download,
        name="special_event_participant_card_download",
    ),
    path(
        "special-events/participants/<uuid:token>/qr-download.png",
        views.special_event_participant_qr_download,
        name="special_event_participant_qr_download",
    ),
    path(
        "special-events/participants/<uuid:token>/text.png",
        views.special_event_participant_text_download,
        name="special_event_participant_text_download",
    ),
]
