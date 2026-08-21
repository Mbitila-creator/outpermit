from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from events.models import Event
from forms_builder.models import (
    EventForm,
    FormQuestion,
    FormSection,
    QuestionOption,
)


EVENT_CODE = "WEUUTz-2026"

def configure_options(question, options):
    active_values = []
    for order, (value, label_sw, label_en) in enumerate(options, start=1):
        active_values.append(value)
        QuestionOption.objects.update_or_create(
            question=question,
            value=value,
            defaults={
                "label_sw": label_sw,
                "label_en": label_en,
                "display_order": order,
                "is_active": True,
            },
        )
    question.options.exclude(value__in=active_values).update(is_active=False)


def configure_question(form, section, *, label_en, label_sw, question_type,
                       order, required=False, options=(), existing_label_en=None,
                       help_en="", help_sw="", condition_question=None,
                       condition_value=""):
    lookup_label = existing_label_en or label_en
    question = FormQuestion.objects.filter(
        section__event_form=form,
        label_en=lookup_label,
    ).first()
    if question is None and lookup_label != label_en:
        question = FormQuestion.objects.filter(
            section__event_form=form,
            label_en=label_en,
        ).first()
    if question is None:
        question = FormQuestion(section=section, label_en=label_en)
    question.section = section
    question.label_en = label_en
    question.label_sw = label_sw
    question.question_type = question_type
    question.display_order = order
    question.is_required = required
    question.help_text_en = help_en
    question.help_text_sw = help_sw
    question.condition_question = condition_question
    question.condition_value = condition_value
    question.is_active = True
    question.save()
    if options:
        configure_options(question, options)
    return question


def configure_section(form, order, title_sw, title_en, description_sw="", description_en=""):
    section = form.sections.filter(title_en=title_en).first()
    if section is None and order == 1:
        section = form.sections.filter(title_en="Participants Views").first()
    if section is None:
        section = FormSection(event_form=form)
    section.title_sw = title_sw
    section.title_en = title_en
    section.description_sw = description_sw
    section.description_en = description_en
    section.display_order = order
    section.condition_question = None
    section.condition_value = ""
    section.is_active = True
    section.save()
    return section


class Command(BaseCommand):
    help = "Create or improve only the WEUUTz-2026 exhibition evaluation form."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required before updating the WEUUTz evaluation form.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("Run again with --confirm to apply the changes.")

        event = Event.objects.filter(code__iexact=EVENT_CODE).first()
        if event is None:
            raise CommandError(f"The {EVENT_CODE} event was not found.")

        event.evaluation_enabled = True
        event.save(update_fields=["evaluation_enabled", "updated_at"])

        form = event.forms.filter(
            form_type=EventForm.FormType.EVALUATION,
        ).order_by("pk").first()
        if form is None:
            form = EventForm(event=event, form_type=EventForm.FormType.EVALUATION)
        form.name_sw = "Dodoso la Tathmini ya Maonesho ya Wiki ya Kitaifa ya Elimu, Ujuzi na Ubunifu"
        form.name_en = "Commemoration Evaluation Questionnaire"
        form.slug = "exhibition-evaluation"
        form.introduction_sw = (
            "Tafadhali jaza dodoso hili kwa niaba ya taasisi yako. Taarifa "
            "zitasaidia kutathmini na kuboresha maadhimisho yajayo."
        )
        form.introduction_en = (
            "Please complete this questionnaire on behalf of your institution. "
            "The information will support evaluation and improvement of future commemorations."
        )
        form.success_message_sw = "Asante. Tathmini yako ya WEUUTz imepokelewa."
        form.success_message_en = "Thank you. Your WEUUTz evaluation has been received."
        form.show_event_summary = True
        form.allow_multiple_submissions = False
        form.is_published = True
        form.is_active = True
        form.save()

        form.sections.update(is_active=False)
        FormQuestion.objects.filter(section__event_form=form).update(is_active=False)

        sections = {
            "A": configure_section(form, 1, "SEHEMU A: TAARIFA ZA MSHIRIKI/TAASISI", "SECTION A: PARTICIPANT/INSTITUTION INFORMATION"),
            "B": configure_section(form, 2, "SEHEMU B: USHIRIKI NA MWITIKIO WA WATEMBELEAJI", "SECTION B: PARTICIPATION AND VISITOR RESPONSE"),
            "C": configure_section(form, 3, "SEHEMU C: TATHMINI YA MAANDALIZI NA UENDESHAJI WA MAONESHO", "SECTION C: EXHIBITION ORGANIZATION AND OPERATIONS", "1 = Duni sana, 2 = Duni, 3 = Wastani, 4 = Nzuri, 5 = Nzuri sana.", "1 = Very poor, 2 = Poor, 3 = Fair, 4 = Good, 5 = Very good."),
            "D": configure_section(form, 4, "SEHEMU D: MANUFAA NA MATOKEO YA USHIRIKI", "SECTION D: PARTICIPATION BENEFITS AND OUTCOMES", "1 = Haijafanikiwa kabisa, 2 = Kidogo, 3 = Wastani, 4 = Imefanikiwa, 5 = Imefanikiwa sana.", "1 = Not achieved, 2 = Slightly, 3 = Moderate, 4 = Achieved, 5 = Highly achieved."),
            "E": configure_section(form, 5, "SEHEMU E: TATHMINI YA JUMLA", "SECTION E: OVERALL EVALUATION"),
            "F": configure_section(form, 6, "SEHEMU F: MAFANIKIO, CHANGAMOTO NA MAPENDEKEZO", "SECTION F: ACHIEVEMENTS, CHALLENGES AND RECOMMENDATIONS"),
        }

        institution_types = (
            ("MINISTRY", "Wizara/Idara ya Serikali", "Ministry/Government department"),
            ("AGENCY", "Wakala/Taasisi ya Serikali", "Government agency/institution"),
            ("LOCAL_GOVERNMENT", "Serikali za Mitaa", "Local government authority"),
            ("UNIVERSITY", "Chuo Kikuu/Chuo cha Elimu ya Juu", "University/Higher education institution"),
            ("TVET", "Chuo cha Ufundi na Mafunzo ya Ufundi Stadi", "Technical/Vocational training institution"),
            ("SCHOOL", "Shule/Taasisi ya Elimu", "School/Education institution"),
            ("RESEARCH", "Taasisi ya Utafiti na Maendeleo", "Research and development institution"),
            ("PRIVATE", "Kampuni/Sekta Binafsi", "Company/Private sector"),
            ("NGO", "Shirika Lisilo la Kiserikali", "Non-governmental organization"),
            ("PARTNER", "Mshirika wa Maendeleo", "Development partner"),
            ("INNOVATOR", "Mbunifu/Mvumbuzi/Mjasiriamali", "Innovator/Inventor/Entrepreneur"),
            ("OTHER", "Nyingine", "Other"),
        )
        service_areas = (
            ("EDUCATION", "Elimu na Mafunzo", "Education and training"),
            ("RESEARCH", "Utafiti na Maendeleo", "Research and development"),
            ("STI", "Sayansi, Teknolojia na Ubunifu", "Science, technology and innovation"),
            ("TVET", "Ujuzi na Mafunzo ya Ufundi", "Skills and vocational training"),
            ("CONSULTANCY", "Huduma za Ushauri", "Consultancy services"),
            ("PRODUCTION", "Uzalishaji/Biashara", "Production/Business"),
            ("SOCIAL", "Huduma za Kijamii", "Social services"),
            ("REGULATION", "Uratibu/Udhibiti", "Coordination/Regulation"),
            ("OTHER", "Nyingine", "Other"),
        )
        generic_rating = tuple((str(i), sw, en) for i, sw, en in (
            (1, "1 – Duni sana", "1 – Very poor"), (2, "2 – Duni", "2 – Poor"),
            (3, "3 – Wastani", "3 – Fair"), (4, "4 – Nzuri", "4 – Good"),
            (5, "5 – Nzuri sana", "5 – Very good"),
        ))

        configure_question(form, sections["A"], label_en="Institution/organization name", label_sw="A1. Jina la Taasisi/Shirika", question_type=FormQuestion.QuestionType.SHORT_TEXT, order=1, required=True)
        institution_type = configure_question(form, sections["A"], label_en="Institution/organization type", label_sw="A2. Aina ya Taasisi/Shirika", question_type=FormQuestion.QuestionType.SINGLE_CHOICE, order=2, required=True, options=institution_types)
        configure_question(form, sections["A"], label_en="Other institution type (specify)", label_sw="A2. Nyingine, taja", question_type=FormQuestion.QuestionType.SHORT_TEXT, order=3, required=True, condition_question=institution_type, condition_value="OTHER")
        service_question = configure_question(form, sections["A"], label_en="Main service/activity areas (select all that apply)", label_sw="A3. Eneo kuu la huduma/shughuli za taasisi yako (Unaweza kuchagua zaidi ya moja)", question_type=FormQuestion.QuestionType.MULTIPLE_CHOICE, order=4, required=True, options=service_areas)
        configure_question(form, sections["A"], label_en="Other service/activity area (specify)", label_sw="A3. Nyingine, taja", question_type=FormQuestion.QuestionType.SHORT_TEXT, order=5, required=True, condition_question=service_question, condition_value="OTHER")
        booths = configure_question(form, sections["A"], label_en="How many booths did your institution have at the exhibition?", label_sw="A4. Taasisi yako ilikuwa na mabanda mangapi katika maonesho?", question_type=FormQuestion.QuestionType.NUMBER, order=6, required=True)
        booths.minimum_value = 0; booths.save(update_fields=["minimum_value", "updated_at"])

        visitor_ranges = (
            ("LT100", "Chini ya 100", "Below 100"), ("100_499", "100–499", "100–499"),
            ("500_999", "500–999", "500–999"), ("1000_2499", "1,000–2,499", "1,000–2,499"),
            ("2500_4999", "2,500–4,999", "2,500–4,999"), ("5000_PLUS", "5,000 au zaidi", "5,000 or more"),
            ("UNKNOWN", "Hatukuweza kukadiria", "Unable to estimate"),
        )
        response_rating = (
            ("1", "1 – Kidogo sana", "1 – Very low"), ("2", "2 – Kidogo", "2 – Low"),
            ("3", "3 – Wastani", "3 – Moderate"), ("4", "4 – Kikubwa", "4 – High"),
            ("5", "5 – Kikubwa sana", "5 – Very high"),
        )
        interest_rating = (
            ("1", "1 – Hawakuvutiwa kabisa", "1 – Not interested at all"), ("2", "2 – Kidogo", "2 – Slightly"),
            ("3", "3 – Wastani", "3 – Moderately"), ("4", "4 – Walivutiwa", "4 – Interested"),
            ("5", "5 – Walivutiwa sana", "5 – Very interested"),
        )
        visitor_groups = (
            ("STUDENTS", "Wanafunzi", "Students"), ("TEACHERS", "Walimu/Wakufunzi", "Teachers/Trainers"),
            ("RESEARCHERS", "Watafiti/Wanazuoni", "Researchers/Academics"), ("ENTREPRENEURS", "Wajasiriamali/Sekta binafsi", "Entrepreneurs/Private sector"),
            ("GOVERNMENT", "Watumishi wa Serikali", "Government employees"), ("INVESTORS", "Wawekezaji/Wafanyabiashara", "Investors/Businesspeople"),
            ("PARENTS", "Wazazi/Walezi", "Parents/Guardians"), ("PUBLIC", "Wananchi kwa ujumla", "General public"),
            ("INTERNATIONAL", "Wageni wa kimataifa", "International visitors"), ("OTHER", "Wengine", "Other"),
        )
        configure_question(form, sections["B"], label_en="Approximately how many people visited your booth during the exhibition?", label_sw="B1. Takribani watu wangapi walitembelea banda lako katika kipindi chote cha maonesho?", question_type=FormQuestion.QuestionType.SINGLE_CHOICE, order=1, required=True, options=visitor_ranges)
        configure_question(form, sections["B"], label_en="How would you rate the public response in visiting your booth?", label_sw="B2. Kwa mtazamo wako, kiwango cha mwitikio wa wananchi katika kutembelea banda lako kilikuwaje?", question_type=FormQuestion.QuestionType.SINGLE_CHOICE, order=2, required=True, options=response_rating)
        configure_question(form, sections["B"], label_en="How interested were visitors in the products, services, technologies or innovations displayed?", label_sw="B3. Wageni waliotembelea banda lako walionesha kiwango gani cha kuvutiwa na bidhaa, huduma, teknolojia au ubunifu mlioonesha?", question_type=FormQuestion.QuestionType.SINGLE_CHOICE, order=3, required=True, options=interest_rating)
        visitor_group_question = configure_question(form, sections["B"], label_en="Which groups visited your booth most? (Select all that apply)", label_sw="B4. Ni makundi gani yalitembelea zaidi banda lako? (Unaweza kuchagua zaidi ya moja)", question_type=FormQuestion.QuestionType.MULTIPLE_CHOICE, order=4, required=True, options=visitor_groups)
        configure_question(form, sections["B"], label_en="Other visitor group (specify)", label_sw="B4. Wengine, taja", question_type=FormQuestion.QuestionType.SHORT_TEXT, order=5, required=True, condition_question=visitor_group_question, condition_value="OTHER")

        c_items = (
            ("Taarifa na mawasiliano kabla ya maonesho", "Information and communication before the exhibition"),
            ("Mfumo/mchakato wa usajili", "Registration system/process"), ("Mapokezi na maelekezo kwa waoneshaji", "Reception and guidance for exhibitors"),
            ("Upangaji na ugawaji wa maeneo ya mabanda", "Planning and allocation of booth spaces"), ("Miundombinu na mazingira ya maonesho", "Exhibition infrastructure and environment"),
            ("Upatikanaji wa umeme na huduma muhimu", "Availability of electricity and essential services"), ("Usafi na huduma za vyoo", "Cleanliness and toilet services"),
            ("Usalama wa watu na mali", "Security of people and property"), ("Uratibu na usaidizi kutoka kwa waandaaji", "Coordination and support from organizers"),
            ("Utangazaji na uhamasishaji wa maonesho", "Exhibition publicity and promotion"), ("Mpangilio wa ratiba na shughuli", "Scheduling and activity coordination"),
            ("Eneo/mahali yalipofanyika maonesho", "Exhibition venue/location"),
        )
        for order, (sw, en) in enumerate(c_items, 1):
            configure_question(form, sections["C"], label_en=f"C{order}. {en}", label_sw=f"C{order}. {sw}", question_type=FormQuestion.QuestionType.SINGLE_CHOICE, order=order, required=True, options=generic_rating)

        achievement_rating = (
            ("1", "1 – Haijafanikiwa kabisa", "1 – Not achieved"), ("2", "2 – Kidogo", "2 – Slightly"),
            ("3", "3 – Wastani", "3 – Moderately"), ("4", "4 – Imefanikiwa", "4 – Achieved"),
            ("5", "5 – Imefanikiwa sana", "5 – Highly achieved"),
        )
        d_items = (
            ("Kutangaza taasisi na shughuli zake", "Promoting the institution and its activities"),
            ("Kutangaza bidhaa/huduma/teknolojia/ubunifu", "Promoting products/services/technology/innovation"),
            ("Kutoa elimu na taarifa kwa wananchi", "Providing education and information to the public"),
            ("Kupata mrejesho kutoka kwa wananchi/wateja", "Receiving feedback from the public/clients"),
            ("Kujenga mitandao na taasisi nyingine", "Networking with other institutions"),
            ("Kuanzisha fursa mpya za ushirikiano", "Creating new collaboration opportunities"),
            ("Kubadilishana maarifa, teknolojia na uzoefu", "Exchanging knowledge, technology and experience"),
            ("Kufikia walengwa wa taasisi", "Reaching the institution's target groups"),
        )
        for order, (sw, en) in enumerate(d_items, 1):
            configure_question(form, sections["D"], label_en=f"D1.{order} {en}", label_sw=f"D1.{order} {sw}", question_type=FormQuestion.QuestionType.SINGLE_CHOICE, order=order, required=True, options=achievement_rating)
        partnership = configure_question(form, sections["D"], label_en="Were any important new collaborations, opportunities or contacts obtained?", label_sw="D2. Je, kuna ushirikiano, fursa au mawasiliano mapya muhimu yaliyopatikana kutokana na maonesho haya?", question_type=FormQuestion.QuestionType.SINGLE_CHOICE, order=9, required=True, options=(("YES", "Ndiyo", "Yes"), ("NO", "Hapana", "No")))
        configure_question(form, sections["D"], label_en="If yes, briefly explain", label_sw="D2. Kama Ndiyo, eleza kwa kifupi", question_type=FormQuestion.QuestionType.LONG_TEXT, order=10, required=True, condition_question=partnership, condition_value="YES")
        configure_question(form, sections["D"], label_en="To what extent did participation meet your institution's expectations?", label_sw="D3. Kwa ujumla, ushiriki katika maonesho haya umekidhi matarajio ya taasisi yako kwa kiwango gani?", question_type=FormQuestion.QuestionType.SINGLE_CHOICE, order=11, required=True, options=achievement_rating)

        satisfaction = (
            ("1", "1 – Sijaridhika kabisa", "1 – Completely dissatisfied"), ("2", "2 – Sijaridhika", "2 – Dissatisfied"),
            ("3", "3 – Wastani", "3 – Neutral"), ("4", "4 – Nimeridhika", "4 – Satisfied"),
            ("5", "5 – Nimeridhika sana", "5 – Very satisfied"),
        )
        future_participation = (
            ("DEFINITELY_YES", "Ndiyo, bila shaka", "Definitely yes"), ("PROBABLY_YES", "Huenda ndiyo", "Probably yes"),
            ("UNSURE", "Sina uhakika", "Not sure"), ("PROBABLY_NO", "Huenda hapana", "Probably no"),
            ("DEFINITELY_NO", "Hapana kabisa", "Definitely no"),
        )
        recommendation = (
            ("1", "1 – Sitapendekeza kabisa", "1 – Definitely would not recommend"), ("2", "2 – Huenda nisipendekeze", "2 – Probably would not recommend"),
            ("3", "3 – Sina uhakika", "3 – Not sure"), ("4", "4 – Nitapendekeza", "4 – Would recommend"),
            ("5", "5 – Nitapendekeza sana", "5 – Strongly recommend"),
        )
        configure_question(form, sections["E"], label_en="Overall satisfaction with exhibition organization and operations", label_sw="E1. Kwa ujumla, umeridhika kwa kiwango gani na maandalizi na uendeshaji wa maonesho?", question_type=FormQuestion.QuestionType.SINGLE_CHOICE, order=1, required=True, options=satisfaction)
        configure_question(form, sections["E"], label_en="Would your institution participate again in future exhibitions?", label_sw="E2. Je, ungependa taasisi yako kushiriki tena katika maonesho yajayo?", question_type=FormQuestion.QuestionType.SINGLE_CHOICE, order=2, required=True, options=future_participation)
        configure_question(form, sections["E"], label_en="Would you recommend that other institutions participate in future exhibitions?", label_sw="E3. Je, ungependekeza taasisi nyingine kushiriki katika maonesho yajayo?", question_type=FormQuestion.QuestionType.SINGLE_CHOICE, order=3, required=True, options=recommendation)

        challenge_options = (
            ("COMMUNICATION", "Mawasiliano/taarifa kutofika kwa wakati", "Late communication/information"), ("REGISTRATION", "Changamoto za usajili", "Registration challenges"),
            ("BOOTH", "Eneo au ukubwa wa banda", "Booth location or size"), ("ELECTRICITY", "Umeme", "Electricity"),
            ("INTERNET", "Intaneti", "Internet"), ("SANITATION", "Usafi/maji/vyoo", "Cleanliness/water/toilets"),
            ("SECURITY", "Usalama", "Security"), ("TRANSPORT", "Usafiri na ufikaji eneo la maonesho", "Transport and venue access"),
            ("LOW_VISITORS", "Idadi ndogo ya wageni", "Low visitor numbers"), ("COST", "Gharama za ushiriki", "Participation costs"),
            ("SCHEDULE", "Ratiba/uratibu wa shughuli", "Schedule/activity coordination"), ("OTHER", "Changamoto nyingine", "Other challenge"),
        )
        configure_question(form, sections["F"], label_en="List the three main achievements gained from participating", label_sw="F1. Taja mafanikio makuu matatu ambayo taasisi yako imeyapata kutokana na kushiriki katika maonesho haya", question_type=FormQuestion.QuestionType.LONG_TEXT, order=1, required=True)
        challenges = configure_question(form, sections["F"], label_en="Main challenges encountered (select all that apply)", label_sw="F2. Ni changamoto zipi kuu mlizokutana nazo wakati wa maandalizi na ushiriki katika maonesho? (Chagua zote zinazohusika)", question_type=FormQuestion.QuestionType.MULTIPLE_CHOICE, order=2, required=True, options=challenge_options)
        configure_question(form, sections["F"], label_en="Other challenge (specify)", label_sw="F2. Changamoto nyingine, taja", question_type=FormQuestion.QuestionType.SHORT_TEXT, order=3, required=True, condition_question=challenges, condition_value="OTHER")
        configure_question(form, sections["F"], label_en="Which was the greatest challenge?", label_sw="F3. Kati ya changamoto ulizotaja, ipi ilikuwa changamoto kubwa zaidi?", question_type=FormQuestion.QuestionType.LONG_TEXT, order=4, required=True)
        configure_question(form, sections["F"], label_en="List three things done well that should continue", label_sw="F4. Taja mambo matatu yaliyofanyika vizuri zaidi katika maonesho haya ambayo ungependa yaendelezwe katika maonesho yajayo", question_type=FormQuestion.QuestionType.LONG_TEXT, order=5, required=True)
        configure_question(form, sections["F"], label_en="List the three most important improvements for future exhibitions", label_sw="F5. Taja mambo matatu muhimu zaidi ambayo ungependa yaboreshwe katika maandalizi na uendeshaji wa maonesho yajayo", question_type=FormQuestion.QuestionType.LONG_TEXT, order=6, required=True, existing_label_en="What should we improve in future exhibitions?")
        configure_question(form, sections["F"], label_en="Other comments or recommendations", label_sw="F6. Maoni au mapendekezo mengine ya kuboresha maonesho yajayo", question_type=FormQuestion.QuestionType.LONG_TEXT, order=7)

        self.stdout.write(self.style.SUCCESS(
            f"Configured {form.name_en}: "
            f"{form.sections.filter(is_active=True).count()} sections, "
            f"{FormQuestion.objects.filter(section__event_form=form, is_active=True).count()} questions."
        ))
