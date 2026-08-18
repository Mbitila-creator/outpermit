from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods

from .forms import SpecialEventParticipantImportForm, special_event_queryset
from .models import (
    Event,
    EventCategory,
    SpecialEventParticipant,
    SpecialEventPublication,
)
from .qr_cards import (
    render_participant_qr_card,
    render_participant_qr_only,
    render_participant_text_image,
)
from .services import import_special_event_participants


def _require_events_permission(user, action="view"):
    if not user.is_active or not user.has_perm(
        f"events.{action}_specialeventparticipant"
    ):
        raise PermissionDenied


def _special_events():
    return [event for event in special_event_queryset() if event.category.is_special_event]


def _active_publications_prefetch():
    return Prefetch(
        "publications",
        queryset=SpecialEventPublication.objects.filter(is_active=True).order_by(
            "source_sheet",
            "source_row_index",
            "research_title",
        ),
        to_attr="active_publications",
    )


def _participant_verification_url(request, participant):
    verification_path = reverse(
        "events:special_event_participant_verify",
        kwargs={"token": participant.verification_token},
    )
    if settings.PUBLIC_BASE_URL:
        return f"{settings.PUBLIC_BASE_URL}{verification_path}"
    return request.build_absolute_uri(verification_path)


def _participant_image_filename(participant, image_type):
    identity = "-".join((
        slugify(participant.event.code) or "event",
        slugify(participant.full_name)[:60],
        str(participant.verification_token)[:8],
    ))
    return f"{identity}-{image_type}.png"


def home(request):
    current_time = timezone.now()

    search_query = request.GET.get("q", "").strip()
    category_slug = request.GET.get("category", "").strip()

    events = (
        Event.objects.select_related(
            "category",
            "venue",
            "venue__council",
            "venue__council__region",
        )
        .filter(
            is_active=True,
            is_public=True,
        )
        .exclude(
            status=Event.Status.CANCELLED,
        )
        .order_by("starts_at")
    )

    if search_query:
        events = events.filter(
            Q(code__icontains=search_query)
            | Q(title_sw__icontains=search_query)
            | Q(title_en__icontains=search_query)
            | Q(description_sw__icontains=search_query)
            | Q(description_en__icontains=search_query)
            | Q(organizer_name_sw__icontains=search_query)
            | Q(organizer_name_en__icontains=search_query)
            | Q(contact_person__icontains=search_query)
            | Q(contact_email__icontains=search_query)
            | Q(contact_phone__icontains=search_query)
        ).distinct()

    if category_slug:
        events = events.filter(
            category__slug=category_slug,
        )

    categories = EventCategory.objects.filter(
        is_active=True,
    ).order_by(
        "display_order",
        "name_sw",
    )

    context = {
        "events": events,
        "categories": categories,
        "search_query": search_query,
        "selected_category": category_slug,
        "current_time": current_time,
    }

    return render(
        request,
        "events/home.html",
        context,
    )


def event_detail(request, event_slug):
    event = get_object_or_404(
        Event.objects.select_related(
            "category",
            "venue",
            "venue__council",
            "venue__council__region",
        ).prefetch_related(
            "forms",
        ),
        slug=event_slug,
        is_active=True,
        is_public=True,
    )

    current_time = timezone.now()

    active_forms = event.forms.filter(
        is_active=True,
        is_published=True,
    ).order_by(
        "form_type",
        "name_sw",
    )

    registration_form = active_forms.filter(
        form_type="REGISTRATION",
    ).first()

    if registration_form is None:
        registration_form = active_forms.filter(
            form_type="EXHIBITOR",
        ).first()

    evaluation_form = active_forms.filter(
        form_type="EVALUATION",
    ).first()

    registration_not_open = (
        event.registration_opens_at
        and current_time < event.registration_opens_at
    )

    registration_closed = (
        event.registration_closes_at
        and current_time > event.registration_closes_at
    )

    registration_available = (
        event.registration_enabled
        and event.status
        in [
            Event.Status.PUBLISHED,
            Event.Status.REGISTRATION_OPEN,
        ]
        and not registration_not_open
        and not registration_closed
        and registration_form is not None
    )

    context = {
        "event": event,
        "active_forms": active_forms,
        "registration_form": registration_form,
        "evaluation_form": evaluation_form,
        "registration_not_open": registration_not_open,
        "registration_closed": registration_closed,
        "registration_available": registration_available,
        "current_time": current_time,
    }

    return render(
        request,
        "events/event_detail.html",
        context,
    )


@login_required(login_url="login")
def special_event_participant_list(request):
    _require_events_permission(request.user)
    events = _special_events()
    selected_event = None
    selected_event_id = request.GET.get("event", "").strip()
    if selected_event_id:
        selected_event = next(
            (event for event in events if str(event.pk) == selected_event_id),
            None,
        )
        if selected_event is None:
            raise PermissionDenied
    elif events:
        selected_event = events[0]

    participants = SpecialEventParticipant.objects.none()
    search_query = request.GET.get("q", "").strip()
    source_sheet = request.GET.get("sheet", "").strip()
    sheet_choices = []
    if selected_event:
        participants = SpecialEventParticipant.objects.filter(
            event=selected_event,
            is_active=True,
        ).annotate(
            publication_count=Count(
                "publications",
                filter=Q(publications__is_active=True),
                distinct=True,
            )
        ).prefetch_related(_active_publications_prefetch())
        sheet_choices = list(
            SpecialEventPublication.objects.filter(
                participant__event=selected_event,
                participant__is_active=True,
                is_active=True,
            )
            .order_by("source_sheet")
            .values_list("source_sheet", flat=True)
            .distinct()
        )
        if search_query:
            researcher_match = (
                Q(full_name__icontains=search_query)
                | Q(institution__icontains=search_query)
            )
            publication_match = Q(publications__is_active=True) & (
                Q(publications__research_title__icontains=search_query)
                | Q(publications__award_category__icontains=search_query)
                | Q(publications__award_year__icontains=search_query)
                | Q(publications__source_number__icontains=search_query)
            )
            participants = participants.filter(
                researcher_match | publication_match
            ).distinct()
        if source_sheet:
            participants = participants.filter(
                publications__source_sheet=source_sheet,
                publications__is_active=True,
            ).distinct()

    paginator = Paginator(
        participants.order_by("full_name", "institution"),
        50,
    )
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "events/special_event_participant_list.html", {
        "events": events,
        "selected_event": selected_event,
        "participants_page": page,
        "participant_count": paginator.count,
        "search_query": search_query,
        "selected_sheet": source_sheet,
        "sheet_choices": sheet_choices,
        "can_import": request.user.has_perm("events.add_specialeventparticipant"),
    })


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def special_event_participant_import(request):
    _require_events_permission(request.user, "add")
    initial = {}
    event_id = request.GET.get("event", "").strip()
    if event_id:
        initial["event"] = event_id
    form = SpecialEventParticipantImportForm(
        request.POST or None,
        request.FILES or None,
        initial=initial,
    )
    if request.method == "POST" and form.is_valid():
        try:
            result = import_special_event_participants(
                event=form.cleaned_data["event"],
                uploaded_file=form.cleaned_data["workbook"],
                user=request.user,
            )
        except ValidationError as exc:
            form.add_error("workbook", exc)
        else:
            messages.success(request, (
                "Import completed: "
                f"{result.researchers_created} researchers added, "
                f"{result.researchers_updated} researchers updated, "
                f"{result.publications_created} publications added and "
                f"{result.publications_updated} publications updated."
            ))
            return redirect(
                f"{reverse('events:special_event_participant_list')}?event={form.cleaned_data['event'].pk}"
            )
    return render(request, "events/special_event_participant_import.html", {
        "form": form,
    })


@login_required(login_url="login")
def special_event_participant_print(request):
    _require_events_permission(request.user)
    events = _special_events()
    selected_event = get_object_or_404(
        Event.objects.select_related("category"),
        pk=request.GET.get("event"),
        is_active=True,
    )
    if selected_event not in events:
        raise PermissionDenied
    participants = SpecialEventParticipant.objects.filter(
        event=selected_event,
        is_active=True,
    ).prefetch_related(_active_publications_prefetch()).order_by("full_name", "institution")
    source_sheet = request.GET.get("sheet", "").strip()
    if source_sheet:
        participants = participants.filter(
            publications__source_sheet=source_sheet,
            publications__is_active=True,
        ).distinct()
    return render(request, "events/special_event_participant_print.html", {
        "selected_event": selected_event,
        "participants": participants,
        "selected_sheet": source_sheet,
    })


@login_required(login_url="login")
def special_event_participant_cards_zip(request):
    _require_events_permission(request.user)
    selected_event = get_object_or_404(
        special_event_queryset(),
        pk=request.GET.get("event"),
    )
    participants = SpecialEventParticipant.objects.select_related("event").filter(
        event=selected_event,
        is_active=True,
    ).prefetch_related(_active_publications_prefetch()).order_by("full_name", "institution")
    source_sheet = request.GET.get("sheet", "").strip()
    if source_sheet:
        participants = participants.filter(
            publications__source_sheet=source_sheet,
            publications__is_active=True,
        ).distinct()

    output = BytesIO()
    safe_event_code = slugify(selected_event.code) or "special-event"
    folder = f"{safe_event_code}-participant-images"
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for participant in participants:
            verification_url = _participant_verification_url(request, participant)
            card = render_participant_qr_card(
                participant,
                verification_url,
            )
            qr_only = render_participant_qr_only(verification_url)
            text_only = render_participant_text_image(participant)
            archive.writestr(
                f"{folder}/combined-cards/{_participant_image_filename(participant, 'combined')}",
                card,
            )
            archive.writestr(
                f"{folder}/qr-only/{_participant_image_filename(participant, 'qr-only')}",
                qr_only,
            )
            archive.writestr(
                f"{folder}/text-only/{_participant_image_filename(participant, 'text-only')}",
                text_only,
            )
    response = HttpResponse(output.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = (
        f'attachment; filename="{safe_event_code}-participant-images.zip"'
    )
    return response


@login_required(login_url="login")
def special_event_participant_cards_word(request):
    from .word_cards import build_editable_participant_cards

    _require_events_permission(request.user)
    selected_event = get_object_or_404(
        special_event_queryset(),
        pk=request.GET.get("event"),
    )
    participants = SpecialEventParticipant.objects.select_related("event").filter(
        event=selected_event,
        is_active=True,
    ).prefetch_related(_active_publications_prefetch()).order_by("full_name", "institution")
    source_sheet = request.GET.get("sheet", "").strip()
    if source_sheet:
        participants = participants.filter(
            publications__source_sheet=source_sheet,
            publications__is_active=True,
        ).distinct()

    document = build_editable_participant_cards(
        participants,
        lambda participant: _participant_verification_url(request, participant),
    )
    safe_event_code = slugify(selected_event.code) or "special-event"
    response = HttpResponse(
        document,
        content_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{safe_event_code}-editable-QR-cards.docx"'
    )
    return response


def special_event_participant_verify(request, token):
    participant = get_object_or_404(
        SpecialEventParticipant.objects.select_related(
            "event",
            "event__category",
        ).prefetch_related(_active_publications_prefetch()),
        verification_token=token,
        is_active=True,
        event__is_active=True,
    )
    return render(request, "events/special_event_participant_verify.html", {
        "participant": participant,
    })


def special_event_participant_qr(request, token):
    participant = get_object_or_404(
        SpecialEventParticipant,
        verification_token=token,
        is_active=True,
        event__is_active=True,
    )
    image = render_participant_qr_only(
        _participant_verification_url(request, participant)
    )
    response = HttpResponse(image, content_type="image/png")
    response["Content-Disposition"] = (
        f'inline; filename="{_participant_image_filename(participant, "qr-only")}"'
    )
    response["Cache-Control"] = "public, max-age=3600"
    return response


def special_event_participant_card_download(request, token):
    participant = get_object_or_404(
        SpecialEventParticipant.objects.select_related("event"),
        verification_token=token,
        is_active=True,
        event__is_active=True,
    )
    card = render_participant_qr_card(
        participant,
        _participant_verification_url(request, participant),
    )
    response = HttpResponse(card, content_type="image/png")
    response["Content-Disposition"] = (
        f'attachment; filename="{_participant_image_filename(participant, "combined")}"'
    )
    return response


def special_event_participant_qr_download(request, token):
    participant = get_object_or_404(
        SpecialEventParticipant.objects.select_related("event"),
        verification_token=token,
        is_active=True,
        event__is_active=True,
    )
    image = render_participant_qr_only(
        _participant_verification_url(request, participant)
    )
    response = HttpResponse(image, content_type="image/png")
    response["Content-Disposition"] = (
        f'attachment; filename="{_participant_image_filename(participant, "qr-only")}"'
    )
    return response


def special_event_participant_text_download(request, token):
    participant = get_object_or_404(
        SpecialEventParticipant.objects.select_related("event"),
        verification_token=token,
        is_active=True,
        event__is_active=True,
    )
    image = render_participant_text_image(participant)
    response = HttpResponse(image, content_type="image/png")
    response["Content-Disposition"] = (
        f'attachment; filename="{_participant_image_filename(participant, "text-only")}"'
    )
    return response
