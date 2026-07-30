from django.shortcuts import render, redirect, get_object_or_404
from django.core.mail import send_mail
from django.conf import settings
from django.http import HttpResponse
from django.db.models import Q
from django.db import IntegrityError
from django.contrib.auth.decorators import login_required, user_passes_test

from openpyxl import Workbook

from .forms import SummitParticipantForm
from .models import SummitParticipant, SummitEvent


def is_event_admin(user):
    return (
        user.is_superuser or
        user.groups.filter(name__in=[
            "System Administrator",
            "Event Manager",
            "Registration Officer",
            "Check-in Officer",
            "Report Viewer",
        ]).exists()
    )


def register_participant(request, event_code):
    event = get_object_or_404(
        SummitEvent,
        code=event_code.upper(),
        is_archived=False
    )

    if not event.is_open:
        return render(request, 'summit/registration_closed.html', {
            'event': event
        })

    duplicate_message = None

    if request.method == 'POST':
        form = SummitParticipantForm(request.POST, request.FILES)

        if form.is_valid():
            participant = form.save(commit=False)
            participant.event = event

            try:
                participant.save()

                message = f"""
New Summit Registration

Registration Number: {participant.registration_number}
Event: {participant.event.name}
Full Name: {participant.full_name}
Institution: {participant.institution}
Designation: {participant.designation}
Phone: {participant.phone}
Email: {participant.email}
Region: {participant.region}
Attendance Type: {participant.attendance_type}
Registered At: {participant.created_at}
"""

                send_mail(
                    subject='New Summit Registration',
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=['mbitila@gmail.com'],
                    fail_silently=True,
                )

                return redirect('summit_success', participant.id)

            except IntegrityError:
                duplicate_message = (
                    "This participant is already registered for this event. "
                    "Please contact the event administrator if you need to update your details."
                )

    else:
        form = SummitParticipantForm()

    return render(request, 'summit/register.html', {
        'form': form,
        'event': event,
        'duplicate_message': duplicate_message,
    })


def summit_success(request, participant_id):
    participant = get_object_or_404(SummitParticipant, id=participant_id)
    return render(request, 'summit/success.html', {'participant': participant})


def participant_badge(request, participant_id):
    participant = get_object_or_404(SummitParticipant, id=participant_id)
    return render(request, 'summit/badge.html', {'participant': participant})


@login_required
def summit_admin_dashboard(request):
    events = SummitEvent.objects.filter(is_archived=False).order_by('-start_date')
    open_events = events.filter(is_open=True)
    closed_events = events.filter(is_open=False)

    participants = SummitParticipant.objects.filter(event__is_archived=False)

    context = {
        'events': events,
        'open_events_count': open_events.count(),
        'closed_events_count': closed_events.count(),
        'total_participants': participants.count(),
        'physical_count': participants.filter(attendance_type='Physical').count(),
        'online_count': participants.filter(attendance_type='Online').count(),
        'checked_in_count': participants.filter(checked_in=True).count(),
    }

    return render(request, 'summit/admin_dashboard.html', context)


@login_required
def participant_list(request):
    event_id = request.GET.get('event_id', '')
    events = SummitEvent.objects.filter(is_archived=False).order_by('-start_date')

    participants = SummitParticipant.objects.filter(
        event__is_archived=False
    ).order_by('-created_at')

    selected_event = None
    if event_id:
        selected_event = get_object_or_404(SummitEvent, id=event_id)
        participants = participants.filter(event=selected_event)

    search_query = request.GET.get('search', '')
    attendance_type = request.GET.get('attendance_type', '')
    region = request.GET.get('region', '')
    checked_in = request.GET.get('checked_in', '')

    page_title = "Registered Participants"
    if checked_in == '1':
        page_title = "Checked-in Participants"

    if search_query:
        participants = participants.filter(
            Q(full_name__icontains=search_query) |
            Q(institution__icontains=search_query) |
            Q(registration_number__icontains=search_query)
        )

    if attendance_type:
        participants = participants.filter(attendance_type=attendance_type)

    if region:
        participants = participants.filter(region__icontains=region)

    if checked_in == '1':
        participants = participants.filter(checked_in=True)

    context = {
        'events': events,
        'selected_event': selected_event,
        'participants': participants,
        'search_query': search_query,
        'attendance_type': attendance_type,
        'region': region,
        'checked_in': checked_in,
        'event_id': event_id,
        'page_title': page_title,
    }

    return render(request, 'summit/participant_list.html', context)


@login_required
@user_passes_test(is_event_admin)
def export_participants_excel(request):
    event_id = request.GET.get('event_id', '')

    participants = SummitParticipant.objects.filter(event__is_archived=False).order_by('created_at')

    if event_id:
        participants = participants.filter(event_id=event_id)

    search_query = request.GET.get('search', '')
    attendance_type = request.GET.get('attendance_type', '')
    region = request.GET.get('region', '')

    if search_query:
        participants = participants.filter(
            Q(full_name__icontains=search_query) |
            Q(institution__icontains=search_query) |
            Q(registration_number__icontains=search_query)
        )

    if attendance_type:
        participants = participants.filter(attendance_type=attendance_type)

    if region:
        participants = participants.filter(region__icontains=region)

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Participants'

    headers = [
        'Event',
        'Registration Number',
        'Full Name',
        'Institution',
        'Designation',
        'Phone',
        'Email',
        'Region',
        'Attendance Type',
        'Checked In',
        'Registered At',
    ]

    worksheet.append(headers)

    for participant in participants:
        worksheet.append([
            participant.event.name if participant.event else '',
            participant.registration_number,
            participant.full_name,
            participant.institution,
            participant.designation,
            participant.phone,
            participant.email,
            participant.region,
            participant.attendance_type,
            'Yes' if participant.checked_in else 'No',
            participant.created_at.strftime('%d/%m/%Y %H:%M'),
        ])

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="event_participants.xlsx"'

    workbook.save(response)

    return response


@login_required
def event_list(request):
    status = request.GET.get('status', '')

    events = SummitEvent.objects.filter(is_archived=False).order_by('-start_date')

    page_title = "Event Management"

    if status == 'open':
        events = events.filter(is_open=True)
        page_title = "Open Events"

    if status == 'closed':
        events = events.filter(is_open=False)
        page_title = "Closed Events"

    return render(request, 'summit/event_list.html', {
        'events': events,
        'status': status,
        'page_title': page_title,
    })


@login_required
def event_details(request, event_id):
    event = get_object_or_404(SummitEvent, id=event_id)

    participants = SummitParticipant.objects.filter(event=event)

    context = {
        'event': event,
        'participants': participants,
        'total_registered': participants.count(),
        'physical_count': participants.filter(attendance_type='Physical').count(),
        'online_count': participants.filter(attendance_type='Online').count(),
        'checked_in_count': participants.filter(checked_in=True).count(),
    }

    return render(request, 'summit/event_details.html', context)


@login_required
@user_passes_test(is_event_admin)
def edit_event(request, event_id):
    event = get_object_or_404(SummitEvent, id=event_id)

    if request.method == 'POST':
        event.name = request.POST.get('name')
        event.code = request.POST.get('code').upper()
        event.venue = request.POST.get('venue')
        event.start_date = request.POST.get('start_date')
        event.end_date = request.POST.get('end_date') or None
        event.save()

        return redirect('event_details', event.id)

    return render(request, 'summit/edit_event.html', {
        'event': event
    })


@login_required
@user_passes_test(is_event_admin)
def open_event(request, event_id):
    event = get_object_or_404(SummitEvent, id=event_id)
    event.is_open = True
    event.save()

    return redirect('event_list')


@login_required
@user_passes_test(is_event_admin)
def close_event(request, event_id):
    event = get_object_or_404(SummitEvent, id=event_id)
    event.is_open = False
    event.save()

    return redirect('event_list')


@login_required
@user_passes_test(is_event_admin)
def archive_event(request, event_id):
    event = get_object_or_404(SummitEvent, id=event_id)
    event.is_archived = True
    event.is_open = False
    event.save()

    return redirect('event_list')


@login_required
@user_passes_test(is_event_admin)
def duplicate_event(request, event_id):
    old_event = get_object_or_404(SummitEvent, id=event_id)

    new_code = f"{old_event.code}_COPY"

    counter = 1
    while SummitEvent.objects.filter(code=new_code).exists():
        counter += 1
        new_code = f"{old_event.code}_COPY{counter}"

    SummitEvent.objects.create(
        name=f"{old_event.name} Copy",
        code=new_code,
        venue=old_event.venue,
        start_date=old_event.start_date,
        end_date=old_event.end_date,
        is_open=False,
        is_archived=False
    )

    return redirect('event_list')


@login_required
@user_passes_test(is_event_admin)
def create_event(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        code = request.POST.get('code')
        venue = request.POST.get('venue')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        start_time = request.POST.get('start_time')
        end_time = request.POST.get('end_time')

        if name and code and venue and start_date:
            SummitEvent.objects.create(
                name=name,
                code=code.upper(),
                venue=venue,
                start_date=start_date,
                end_date=end_date if end_date else None,
                start_time=start_time if start_time else None,
                end_time=end_time if end_time else None,
                is_open=True,
                is_archived=False
            )

            return redirect('event_list')

    return render(request, 'summit/create_event.html')

@login_required
@user_passes_test(is_event_admin)
def activate_event(request, event_id):
    # Old compatibility route. Multi-event logic now uses open/close.
    event = get_object_or_404(SummitEvent, id=event_id)
    event.is_open = True
    event.save()

    return redirect('event_list')