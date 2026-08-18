from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from events.models import Event, EventCategory, Venue
from forms_builder.models import EventForm, FormQuestion, FormSection, QuestionOption
from forms_builder.services import public_form_path, sync_badge_identity_from_answers
from permits.models import Department

from conferences.models import (
    ConferenceCallForPapers,
    ConferenceProgrammeItem,
    ConferenceSession,
)
from conferences.guiding_questions import configure_guiding_questions


EVENT_CODE = "NESIF-2026"
FORM_SLUG = "national-forum-registration"
TZ = ZoneInfo("Africa/Dar_es_Salaam")

INVITATION = """The Ministry of Education, Science and Technology warmly welcomes you to the National Education, Research, Skills and Innovation Forum, held as part of the National Education, Skills and Innovation Week, taking place from 15th to 24th August 2026 at the Usagara Secondary School Sports Grounds, Tanga City.

The celebrations are guided by the theme:
“Education, Skills and Innovation: Pathway to Achieving the National Development Vision 2050.”

We are particularly pleased to welcome you to the following key sessions:

Session: Basic Education Session
Date: 17th August 2026
Time: 09:00 – 15:00 Hrs

Session: Higher Education and TVET Session
Date: 19th August 2026
Time: 09:00 – 15:00 Hrs

Session: Science, Technology and Innovation Session
Date: 21st August 2026
Time: 09:00 – 15:00 Hrs

These sessions provide an important platform for leaders and all stakeholders to engage in strategic dialogue, share experiences and good practices, identify opportunities for collaboration, and discuss practical measures for strengthening education, research, science, technology and innovation in Tanzania.

Apart from the sessions, the Forum will include the Fursa Women and Youth Innovation Clinic workshop under the Tanzania Commission for Science and Technology (COSTECH), on 22nd August 2026.

The Forum brings together stakeholders from Government, higher education and research institutions, development partners, civil society, private sector, technology companies, innovation centres and other key actors to explore how education, research, skills and innovation can contribute more effectively to productivity, technological capability, value addition, employment and sustainable national development towards Vision 2050.

Your insights, experience and institutional perspectives are highly valued in these discussions. We therefore look forward to your active participation and valuable contribution to making these sessions meaningful and impactful.

Karibuni sana Tanga, na karibu katika kujenga Tanzania yenye Elimu Bora, Ujuzi stahiki na Ubunifu unaochochea maendeleo ya Taifa kuelekea Dira ya Taifa ya Maendeleo 2050.

Ministry of Education, Science and Technology
National Education, Research, Skills and Innovation Forum – 2026"""


class Command(BaseCommand):
    help = "Create or update the 2026 National Forum public registration form."

    @transaction.atomic
    def handle(self, *args, **options):
        dsti = Department.objects.get(code="DSTI", is_active=True)
        category = EventCategory.objects.filter(
            Q(code__iexact="CONFERENCE") | Q(name_en__iexact="Conference")
        ).first()
        if category is None:
            category = EventCategory.objects.create(
                code="CONFERENCE",
                name_sw="Kongamano",
                name_en="Conference",
                slug="conference",
                description_sw="Makongamano na majukwaa ya kitaifa.",
                description_en="Conferences and national forums.",
                display_order=5,
            )
        elif category.code.upper() != "CONFERENCE":
            category.code = "CONFERENCE"
            category.save(update_fields=["code", "updated_at"])

        venue = Venue.objects.filter(
            name="Usagara Secondary School Sports Grounds",
            council__isnull=True,
        ).first()
        if venue is None:
            venue = Venue.objects.create(
                name="Usagara Secondary School Sports Grounds",
                address="Tanga City, Tanzania",
                venue_type=Venue.VenueType.OUTDOOR,
            )

        event, _ = Event.objects.update_or_create(
            code=EVENT_CODE,
            defaults={
                "category": category,
                "owning_department": dsti,
                "venue": venue,
                "title_sw": "Kongamano la Kitaifa la Elimu, Utafiti, Ujuzi na Ubunifu",
                "title_en": "National Education, Research, Skills and Innovation Forum",
                "description_sw": "Kongamano la kitaifa kuelekea Dira ya Maendeleo 2050.",
                "description_en": "A national forum advancing education, research, skills and innovation towards Vision 2050.",
                "organizer_name_sw": "Wizara ya Elimu, Sayansi na Teknolojia",
                "organizer_name_en": "Ministry of Education, Science and Technology",
                "registration_opens_at": None,
                "registration_closes_at": None,
                "starts_at": datetime(2026, 8, 15, 9, 0, tzinfo=TZ),
                "ends_at": datetime(2026, 8, 24, 18, 0, tzinfo=TZ),
                "status": Event.Status.REGISTRATION_OPEN,
                "is_public": True,
                "registration_enabled": True,
                "qr_checkin_enabled": True,
                "badge_enabled": True,
            },
        )

        event_form, _ = EventForm.objects.update_or_create(
            event=event,
            slug=FORM_SLUG,
            defaults={
                "name_sw": "Usajili wa Kongamano la Kitaifa 2026",
                "name_en": "National Forum Registration 2026",
                "form_type": EventForm.FormType.REGISTRATION,
                "introduction_sw": INVITATION,
                "introduction_en": INVITATION,
                "show_event_summary": True,
                "success_message_sw": "Usajili wako umepokelewa. Hifadhi namba yako ya kumbukumbu na QR ya mshiriki.",
                "success_message_en": "Your registration has been received. Keep your reference number and participant QR code.",
                "requires_login": False,
                "opens_at": None,
                "closes_at": None,
                "allow_multiple_submissions": False,
                "is_published": True,
                "is_active": True,
            },
        )

        ConferenceCallForPapers.objects.update_or_create(
            event=event,
            defaults={
                "title": "Call for Abstracts and Papers",
                "introduction": (
                    "Researchers, practitioners, innovators and institutions are invited "
                    "to submit abstracts or full papers for consideration in the National "
                    "Education, Research, Skills and Innovation Forum 2026."
                ),
                "guidelines": (
                    "Provide the paper title, thematic area, corresponding-author details "
                    "and an abstract describing the problem, methods, findings and contribution.\n"
                    "Abstracts must contain between 20 and 1,000 words.\n"
                    "Full-paper submissions must include a PDF, DOC or DOCX file not exceeding 10 MB.\n"
                    "Accepted submissions may be assigned to an oral, poster, panel or workshop session."
                ),
                "opens_at": None,
                "closes_at": None,
                "is_published": True,
                "is_active": True,
            },
        )

        personal, _ = FormSection.objects.update_or_create(
            event_form=event_form,
            title_en="Participant Information",
            defaults={
                "title_sw": "Participant Information",
                "description_en": "Enter the details of the person who will attend.",
                "description_sw": "Enter the details of the person who will attend.",
                "display_order": 1,
                "is_active": True,
            },
        )
        question_specs = [
            (
                "Full Name",
                FormQuestion.QuestionType.SHORT_TEXT,
                True,
                1,
                "Enter the participant's first, middle and last name in this one field.",
            ),
            (
                "Institution Name",
                FormQuestion.QuestionType.SHORT_TEXT,
                True,
                2,
                "Enter the university, organization, company or ministry.",
            ),
            (
                "Position / Title",
                FormQuestion.QuestionType.SHORT_TEXT,
                False,
                3,
                "Optional, for example Director, Lecturer or Student.",
            ),
            ("Email Address", FormQuestion.QuestionType.EMAIL, True, 4, ""),
            ("Phone Number", FormQuestion.QuestionType.PHONE, True, 5, ""),
        ]
        for label, question_type, required, order, help_text in question_specs:
            FormQuestion.objects.update_or_create(
                section=personal,
                label_en=label,
                defaults={
                    "label_sw": label,
                    "question_type": question_type,
                    "help_text_en": help_text,
                    "help_text_sw": help_text,
                    "is_required": required,
                    "display_order": order,
                    "is_active": True,
                },
            )

        attendance, _ = FormSection.objects.update_or_create(
            event_form=event_form,
            title_en="Session Selection",
            defaults={
                "title_sw": "Session Selection",
                "description_en": "You may select one or more sessions.",
                "description_sw": "You may select one or more sessions.",
                "display_order": 2,
                "is_active": True,
            },
        )
        session_question, _ = FormQuestion.objects.update_or_create(
            section=attendance,
            label_en="Which session(s) will you attend?",
            defaults={
                "label_sw": "Which session(s) will you attend?",
                "question_type": FormQuestion.QuestionType.MULTIPLE_CHOICE,
                "help_text_en": "Select all sessions that apply.",
                "help_text_sw": "Select all sessions that apply.",
                "is_required": True,
                "display_order": 1,
                "is_active": True,
            },
        )
        session_options = [
            ("BASIC_EDUCATION_17_AUG", "Basic Education Session — 17 August 2026, 09:00–15:00 Hrs"),
            ("HIGHER_EDUCATION_TVET_19_AUG", "Higher Education and TVET Session — 19 August 2026, 09:00–15:00 Hrs"),
            ("STI_21_AUG", "Science, Technology and Innovation Session — 21 August 2026, 09:00–15:00 Hrs"),
            ("FURSA_CLINIC_22_AUG", "Fursa Women and Youth Innovation Clinic (COSTECH) — 22 August 2026"),
        ]
        active_values = []
        for order, (value, label) in enumerate(session_options, start=1):
            active_values.append(value)
            QuestionOption.objects.update_or_create(
                question=session_question,
                value=value,
                defaults={
                    "label_sw": label,
                    "label_en": label,
                    "display_order": order,
                    "is_active": True,
                },
            )
        session_question.options.exclude(value__in=active_values).update(is_active=False)
        session_records = [
            (
                "BASIC-EDUCATION",
                "Basic Education Session",
                datetime(2026, 8, 17, 9, 0, tzinfo=TZ),
                datetime(2026, 8, 17, 15, 0, tzinfo=TZ),
                "BASIC_EDUCATION_17_AUG",
            ),
            (
                "HIGHER-EDUCATION-TVET",
                "Higher Education and TVET Session",
                datetime(2026, 8, 19, 9, 0, tzinfo=TZ),
                datetime(2026, 8, 19, 15, 0, tzinfo=TZ),
                "HIGHER_EDUCATION_TVET_19_AUG",
            ),
            (
                "STI",
                "Science, Technology and Innovation Session",
                datetime(2026, 8, 21, 9, 0, tzinfo=TZ),
                datetime(2026, 8, 21, 15, 0, tzinfo=TZ),
                "STI_21_AUG",
            ),
            (
                "FURSA-CLINIC",
                "Fursa Women and Youth Innovation Clinic (COSTECH)",
                datetime(2026, 8, 22, 9, 0, tzinfo=TZ),
                datetime(2026, 8, 22, 15, 0, tzinfo=TZ),
                "FURSA_CLINIC_22_AUG",
            ),
        ]
        for order, (code, title, starts_at, ends_at, option_value) in enumerate(
            session_records,
            start=1,
        ):
            session, _ = ConferenceSession.objects.update_or_create(
                event=event,
                code=code,
                defaults={
                    "title": title,
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                    "venue_name": venue.name,
                    "registration_option_value": option_value,
                    "display_order": order,
                    "is_active": True,
                },
            )
            programme_specs = [
                (
                    "OPENING",
                    ConferenceProgrammeItem.ItemType.OPENING,
                    "Opening and welcome",
                    starts_at.replace(hour=9, minute=0),
                    starts_at.replace(hour=9, minute=30),
                    "Welcome, introductions and session objectives.",
                ),
                (
                    "STRATEGIC-DIALOGUE",
                    (
                        ConferenceProgrammeItem.ItemType.WORKSHOP
                        if code == "FURSA-CLINIC"
                        else ConferenceProgrammeItem.ItemType.PANEL
                    ),
                    f"{title}: Strategic dialogue",
                    starts_at.replace(hour=9, minute=30),
                    starts_at.replace(hour=12, minute=0),
                    "Presentations and moderated stakeholder discussion.",
                ),
                (
                    "LUNCH-BREAK",
                    ConferenceProgrammeItem.ItemType.BREAK,
                    "Lunch and networking break",
                    starts_at.replace(hour=12, minute=0),
                    starts_at.replace(hour=13, minute=0),
                    "",
                ),
                (
                    "PRIORITY-ACTIONS",
                    ConferenceProgrammeItem.ItemType.PANEL,
                    "Priority actions and stakeholder commitments",
                    starts_at.replace(hour=13, minute=0),
                    starts_at.replace(hour=14, minute=30),
                    "Agreement on practical actions, responsibilities and collaboration opportunities.",
                ),
                (
                    "CLOSING",
                    ConferenceProgrammeItem.ItemType.CLOSING,
                    "Summary and closing",
                    starts_at.replace(hour=14, minute=30),
                    starts_at.replace(hour=15, minute=0),
                    "Session conclusions and next steps.",
                ),
            ]
            for programme_order, (
                programme_code,
                item_type,
                programme_title,
                programme_starts,
                programme_ends,
                description,
            ) in enumerate(programme_specs, start=1):
                ConferenceProgrammeItem.objects.get_or_create(
                    session=session,
                    code=programme_code,
                    defaults={
                        "item_type": item_type,
                        "title": programme_title,
                        "description": description,
                        "starts_at": programme_starts,
                        "ends_at": programme_ends,
                        "venue_name": session.venue_name,
                        "is_published": True,
                        "display_order": programme_order,
                        "is_active": True,
                    },
                )

        configure_guiding_questions(event_form)

        for submission in event_form.submissions.filter(
            is_active=True,
            is_complete=True,
        ):
            sync_badge_identity_from_answers(submission)

        self.stdout.write(self.style.SUCCESS("Conference registration is ready."))
        self.stdout.write(f"Event: {event.code} — {event.title_en}")
        self.stdout.write(f"Public form: {public_form_path(event_form, language='en')}")
        self.stdout.write(f"Public programme: /en/conferences/{event.slug}/programme/")
        self.stdout.write(f"Paper submission: /en/conferences/{event.slug}/papers/submit/")
        self.stdout.write("Staff QR centre: /en/staff/conferences/")
