import csv
from io import BytesIO
from io import StringIO
from pathlib import Path
from urllib.parse import urljoin

import qrcode
from PIL import Image, ImageDraw, ImageFont
from django.conf import settings
from django.contrib.staticfiles import finders
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.html import format_html
from django.utils.translation import gettext as _

from .models import FormQuestion, QuantityPricingRule


def payment_amount_for_submission(submission):
    """Calculate a fixed fee or a configured first-plus-additional quantity fee."""
    event = submission.event_form.event
    try:
        rule = event.quantity_pricing_rule
    except QuantityPricingRule.DoesNotExist:
        return event.participation_fee
    if not rule.is_active:
        return event.participation_fee

    answer = submission.answers.filter(
        question=rule.quantity_question,
    ).first()
    if not answer or answer.number_value is None:
        return None
    quantity = answer.number_value
    if quantity < 1 or quantity != quantity.to_integral_value():
        return None
    return (
        rule.first_unit_amount
        + ((int(quantity) - 1) * rule.additional_unit_amount)
    )


def public_form_path(event_form, language="sw"):
    with translation.override(language):
        return reverse(
            "forms_builder:public_event_form",
            kwargs={
                "event_slug": event_form.event.slug,
                "form_slug": event_form.slug,
            },
        )


def public_form_url(event_form, request=None, language="sw"):
    path = public_form_path(event_form, language=language)
    base_url = settings.PUBLIC_BASE_URL

    if base_url:
        return urljoin(f"{base_url}/", path.lstrip("/"))

    if request is not None:
        return request.build_absolute_uri(path)

    return path


def booth_detail_url(booth, request=None, language="sw"):
    with translation.override(language):
        path = reverse(
            "forms_builder:booth_detail",
            kwargs={"public_token": booth.public_token},
        )
    base_url = settings.PUBLIC_BASE_URL

    if base_url:
        return urljoin(f"{base_url}/", path.lstrip("/"))

    if request is not None:
        return request.build_absolute_uri(path)

    return path


def participant_badge_path(submission, language="sw"):
    with translation.override(language):
        return reverse(
            "forms_builder:participant_badge",
            kwargs={"participant_token": submission.participant_token},
        )


def participant_certificate_path(submission, language="sw"):
    with translation.override(language):
        return reverse(
            "forms_builder:participant_certificate",
            kwargs={"participant_token": submission.participant_token},
        )


def certificate_number(submission):
    certificate = getattr(submission, "certificate_record", None)
    if certificate and certificate.certificate_number:
        return certificate.certificate_number
    event_year = timezone.localtime(
        submission.event_form.event.starts_at
    ).year
    short_token = str(submission.participant_token).replace("-", "")[:10].upper()
    return f"CERT-{event_year}-{short_token}"


def event_date_range(event, language="sw"):
    starts_at = timezone.localtime(event.starts_at)
    ends_at = timezone.localtime(event.ends_at)
    swahili_months = (
        "Januari",
        "Februari",
        "Machi",
        "Aprili",
        "Mei",
        "Juni",
        "Julai",
        "Agosti",
        "Septemba",
        "Oktoba",
        "Novemba",
        "Desemba",
    )

    def month_name(value):
        if language == "sw":
            return swahili_months[value.month - 1]
        return date_format(value, "F")

    with translation.override(language):
        if starts_at.date() == ends_at.date():
            return f"{starts_at.day} {month_name(starts_at)} {starts_at.year}"

        if starts_at.year == ends_at.year and starts_at.month == ends_at.month:
            return (
                f"{starts_at.day}–{ends_at.day} "
                f"{month_name(ends_at)} {ends_at.year}"
            )

        if starts_at.year == ends_at.year:
            return (
                f"{starts_at.day} {month_name(starts_at)}–"
                f"{ends_at.day} {month_name(ends_at)} {ends_at.year}"
            )

        return (
            f"{starts_at.day} {month_name(starts_at)} {starts_at.year}–"
            f"{ends_at.day} {month_name(ends_at)} {ends_at.year}"
        )


def certificate_verification_url(submission, request=None, language="sw"):
    with translation.override(language):
        path = reverse(
            "forms_builder:certificate_verification",
            kwargs={"participant_token": submission.participant_token},
        )
    base_url = settings.PUBLIC_BASE_URL

    if base_url:
        return urljoin(f"{base_url}/", path.lstrip("/"))

    if request is not None:
        return request.build_absolute_uri(path)

    return path


def participant_badge_url(submission, request=None, language="sw"):
    path = participant_badge_path(submission, language=language)
    base_url = settings.PUBLIC_BASE_URL

    if base_url:
        return urljoin(f"{base_url}/", path.lstrip("/"))

    if request is not None:
        return request.build_absolute_uri(path)

    return path


def participant_check_in_url(submission, request=None, language="sw"):
    with translation.override(language):
        path = reverse(
            "checkin:participant",
            kwargs={"participant_token": submission.participant_token},
        )
    path = f"{path}?auto=1"
    base_url = settings.PUBLIC_BASE_URL

    if base_url:
        return urljoin(f"{base_url}/", path.lstrip("/"))

    if request is not None:
        return request.build_absolute_uri(path)

    return path


def sync_badge_identity_from_answers(submission):
    badge_name = ""
    badge_organization = ""
    badge_position = ""

    answers = submission.answers.select_related("question").all()
    for answer in answers:
        label_en = answer.question.label_en.strip().casefold()
        label_sw = answer.question.label_sw.strip().casefold()
        value = answer.text_value.strip()

        if not value:
            continue

        if label_en in {
            "representative name",
            "participant name",
            "full name",
        } or label_sw in {
            "jina la mwakilishi",
            "jina la mshiriki",
            "jina kamili",
        }:
            badge_name = value

        if label_en in {
            "institution name",
            "organization name",
            "organisation name",
        } or label_sw in {
            "jina la taasisi",
            "jina la shirika",
        }:
            badge_organization = value

        if label_en in {
            "position / title",
            "position",
            "job title",
        } or label_sw in {
            "cheo / wadhifa",
            "cheo",
            "wadhifa",
        }:
            badge_position = value

    submission.badge_name = badge_name or submission.badge_name
    submission.badge_organization = (
        badge_organization or submission.badge_organization
    )
    if submission.event_form.event.category.is_conference:
        submission.badge_title = badge_position
    else:
        submission.badge_title = (
            "Representative" if submission.language == "en" else "Mwakilishi"
        )
    submission.save(
        update_fields=[
            "badge_name",
            "badge_organization",
            "badge_title",
            "updated_at",
        ]
    )


INSTITUTION_CERTIFICATE_EVENT_CODES = {"WEUUTZ-2026"}


def certificate_is_for_institution(submission):
    """Return whether the event awards its certificate to the institution."""
    return (
        submission.event_form.event.code.strip().upper()
        in INSTITUTION_CERTIFICATE_EVENT_CODES
        and bool(submission.badge_organization.strip())
    )


def certificate_recipient_name(submission):
    if certificate_is_for_institution(submission):
        return submission.badge_organization.strip()
    return submission.badge_display_name


def certificate_qr_logo_path(event):
    if event.logo:
        try:
            logo_path = Path(event.logo.path)
            if logo_path.is_file():
                return str(logo_path)
        except (NotImplementedError, OSError, ValueError):
            pass
    return finders.find("logo/moest_logo.png")


def generate_qr_png(value, logo_path=None, fill_color="#000000"):
    if logo_path is None:
        logo_path = finders.find("logo/moest_logo.png")
    qr_code = qrcode.QRCode(
        error_correction=(
            qrcode.constants.ERROR_CORRECT_H
            if logo_path
            else qrcode.constants.ERROR_CORRECT_M
        ),
        box_size=10,
        border=4,
    )
    qr_code.add_data(value)
    qr_code.make(fit=True)

    image = qr_code.make_image(
        fill_color=fill_color,
        back_color="#ffffff",
    ).convert("RGBA")

    if logo_path:
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo_limit = max(24, int(image.width * 0.16))
            logo.thumbnail((logo_limit, logo_limit), Image.Resampling.LANCZOS)
            padding = max(5, int(image.width * 0.018))
            panel_width = logo.width + (padding * 2)
            panel_height = logo.height + (padding * 2)
            panel = Image.new("RGBA", (panel_width, panel_height), "#ffffff")
            panel.paste(logo, (padding, padding), logo)
            position = (
                (image.width - panel_width) // 2,
                (image.height - panel_height) // 2,
            )
            image.alpha_composite(panel, position)
        except (OSError, ValueError):
            pass

    output = BytesIO()
    image.convert("RGB").save(output, format="PNG")
    return output.getvalue()


def _certificate_font(size, bold=False, serif=False):
    if serif:
        font_names = (
            ("DejaVuSerif-Bold.ttf", "Times New Roman Bold.ttf")
            if bold
            else ("DejaVuSerif.ttf", "Times New Roman.ttf")
        )
    else:
        font_names = (
            ("DejaVuSans-Bold.ttf", "Arial Bold.ttf")
            if bold
            else ("DejaVuSans.ttf", "Arial.ttf")
        )
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _ordinal_suffix(day):
    if 10 <= day % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def _ordinal_day(day, superscript=False):
    suffix = _ordinal_suffix(day)
    if superscript:
        suffix = {
            "st": "ˢᵗ",
            "nd": "ⁿᵈ",
            "rd": "ʳᵈ",
            "th": "ᵗʰ",
        }[suffix]
    return f"{day}{suffix}"


def _weuutz_event_location(event):
    location = "Tanga"
    venue = getattr(event, "venue", None)
    council = getattr(venue, "council", None) if venue else None
    region = getattr(council, "region", None) if council else None
    if region:
        location = (
            getattr(region, "name_en", "")
            or getattr(region, "name_sw", "")
            or location
        )
    return location


def weuutz_event_sentence(event, superscript=False):
    starts_at = timezone.localtime(event.starts_at)
    ends_at = timezone.localtime(event.ends_at)
    if starts_at.month == ends_at.month and starts_at.year == ends_at.year:
        date_range = (
            f"{_ordinal_day(starts_at.day, superscript)} to "
            f"{_ordinal_day(ends_at.day, superscript)} "
            f"{ends_at.strftime('%B')}, {ends_at.year}"
        )
    else:
        date_range = (
            f"{_ordinal_day(starts_at.day, superscript)} "
            f"{starts_at.strftime('%B')}, {starts_at.year} to "
            f"{_ordinal_day(ends_at.day, superscript)} "
            f"{ends_at.strftime('%B')}, {ends_at.year}"
        )

    return (
        "Participated in the National Education, Skills and Innovation Week "
        f"{starts_at.year} Exhibitions which was held from {date_range} "
        f"in {_weuutz_event_location(event)}."
    )


def weuutz_event_sentence_html(event):
    starts_at = timezone.localtime(event.starts_at)
    ends_at = timezone.localtime(event.ends_at)
    start_suffix = _ordinal_suffix(starts_at.day)
    end_suffix = _ordinal_suffix(ends_at.day)
    location = _weuutz_event_location(event)
    if starts_at.month == ends_at.month and starts_at.year == ends_at.year:
        return format_html(
            "Participated in the National Education, Skills and Innovation "
            "Week {} Exhibitions which was held from {}<sup>{}</sup> to "
            "{}<sup>{}</sup> {}, {} in {}.",
            starts_at.year,
            starts_at.day,
            start_suffix,
            ends_at.day,
            end_suffix,
            ends_at.strftime("%B"),
            ends_at.year,
            location,
        )
    return format_html(
        "Participated in the National Education, Skills and Innovation Week "
        "{} Exhibitions which was held from {}<sup>{}</sup> {}, {} to "
        "{}<sup>{}</sup> {}, {} in {}.",
        starts_at.year,
        starts_at.day,
        start_suffix,
        starts_at.strftime("%B"),
        starts_at.year,
        ends_at.day,
        end_suffix,
        ends_at.strftime("%B"),
        ends_at.year,
        location,
    )


def _draw_centered_fitted(draw, text, y, width, size, max_width, fill, **font_kwargs):
    font = _certificate_font(size, **font_kwargs)
    while size > 22:
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            break
        size -= 2
        font = _certificate_font(size, **font_kwargs)
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)
    return font


def _draw_centered_wrapped(draw, text, y, width, font, max_width, fill, spacing=12):
    words = text.split()
    lines = []
    current = []
    for word in words:
        candidate = " ".join((*current, word))
        box = draw.textbbox((0, 0), candidate, font=font)
        if current and box[2] - box[0] > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))

    line_height = draw.textbbox((0, 0), "Ag", font=font)[3]
    for index, line in enumerate(lines):
        box = draw.textbbox((0, 0), line, font=font)
        draw.text(
            ((width - (box[2] - box[0])) / 2, y + index * (line_height + spacing)),
            line,
            font=font,
            fill=fill,
        )
    return len(lines) * line_height + max(0, len(lines) - 1) * spacing


def _generate_weuutz_certificate_pdf(submission, verification_url):
    event = submission.event_form.event
    recipient_name = certificate_recipient_name(submission)
    short_certificate_number = certificate_number(submission)
    width, height = 1684, 1191
    image = Image.new("RGB", (width, height), "#00a651")
    draw = ImageDraw.Draw(image)

    # Mirrored Tanzanian flag-inspired corners: left/right and top/bottom match.
    corner_polygons = (
        (((1120, 0), (width, 0), (width, 430), (1510, 520)), "#00a6dd"),
        (((1260, 0), (width, 0), (width, 285), (1510, 470)), "#f9d616"),
        (((1370, 0), (width, 0), (width, 205), (1510, 405)), "#050505"),
    )
    for polygon, fill in corner_polygons:
        for flip_x, flip_y in ((False, False), (True, False), (False, True), (True, True)):
            mirrored = tuple((
                width - x if flip_x else x,
                height - y if flip_y else y,
            ) for x, y in polygon)
            draw.polygon(mirrored, fill=fill)

    # Keep the PDF frame deliberately slim.  A wide raster frame becomes
    # visually much heavier when the image is embedded into an A4 PDF.
    frame = (28, 24, width - 28, height - 24)
    panel = (40, 36, width - 40, height - 36)
    draw.rounded_rectangle(frame, radius=12, fill="#073b22")
    draw.rounded_rectangle(
        panel,
        radius=6,
        fill="#fffefb",
        outline="#d6d6d6",
        width=2,
    )

    black = "#080808"
    green = "#438f24"
    blue = "#1747c9"
    _draw_centered_fitted(
        draw, "THE UNITED REPUBLIC OF TANZANIA", 105, width, 43, width - 260,
        black, bold=True, serif=True,
    )
    _draw_centered_fitted(
        draw, "MINISTRY OF EDUCATION, SCIENCE AND TECHNOLOGY", 188, width,
        40, width - 250, black, bold=True, serif=True,
    )

    logo_path = finders.find("logo/moest_logo.png")
    if logo_path:
        emblem = Image.open(logo_path).convert("RGBA")
        emblem.thumbnail((205, 205), Image.Resampling.LANCZOS)
        image.paste(
            emblem,
            ((width - emblem.width) // 2, 250),
            emblem,
        )

    _draw_centered_fitted(
        draw, "CERTIFICATION OF PARTICIPATION", 475, width, 48, width - 400,
        green, bold=True, serif=True,
    )
    _draw_centered_fitted(
        draw, "THIS IS TO CERTIFY THAT", 570, width, 38, width - 500,
        black, serif=True,
    )
    _draw_centered_fitted(
        draw, recipient_name.upper(), 650, width, 54, width - 230,
        blue, bold=True, serif=True,
    )
    draw.line((245, 725, width - 245, 725), fill="#8d8d8d", width=2)

    statement = weuutz_event_sentence(event, superscript=True)
    _draw_centered_wrapped(
        draw,
        statement,
        765,
        width,
        _certificate_font(30, serif=True),
        width - 330,
        black,
        spacing=16,
    )

    # Permanent Secretary signature block.
    signature_path = finders.find(
        "images/weuutz-permanent-secretary-signature.png"
    )
    if signature_path:
        signature = Image.open(signature_path).convert("RGBA")
        signature.thumbnail((390, 105), Image.Resampling.LANCZOS)
        signature_x = (width - signature.width) // 2
        signature_y = 940 - signature.height - 4
        image.paste(signature, (signature_x, signature_y), signature)
    draw.line((520, 940, 1060, 940), fill="#777777", width=2)
    _draw_centered_fitted(
        draw, "Prof. Carolyne I. Nombo", 955, width, 30, 520,
        black, serif=True,
    )
    _draw_centered_fitted(
        draw, "PERMANENT SECRETARY", 1005, width, 30, 520,
        black, bold=True, serif=True,
    )

    qr_image = Image.open(BytesIO(generate_qr_png(
        verification_url,
        logo_path=certificate_qr_logo_path(event),
    ))).convert("RGB")
    qr_image = qr_image.resize((180, 180), Image.Resampling.LANCZOS)
    qr_x, qr_y = width - 330, 855
    image.paste(qr_image, (qr_x, qr_y))
    number_font_size = 14
    number_font = _certificate_font(number_font_size, bold=True)
    box = draw.textbbox((0, 0), short_certificate_number, font=number_font)
    while box[2] - box[0] > 280 and number_font_size > 9:
        number_font_size -= 1
        number_font = _certificate_font(number_font_size, bold=True)
        box = draw.textbbox((0, 0), short_certificate_number, font=number_font)
    draw.text(
        (qr_x + (180 - (box[2] - box[0])) / 2, 1044),
        short_certificate_number,
        font=number_font,
        fill=black,
    )

    output = BytesIO()
    image.save(output, format="PDF", resolution=150)
    return output.getvalue()


def generate_certificate_pdf(submission, verification_url, language="sw"):
    event = submission.event_form.event
    if certificate_is_for_institution(submission):
        return _generate_weuutz_certificate_pdf(submission, verification_url)

    short_certificate_number = certificate_number(submission)
    formatted_event_dates = event_date_range(event, language=language)
    event_name = event.title_en if language == "en" else event.title_sw
    recipient_name = certificate_recipient_name(submission)
    institution_certificate = certificate_is_for_institution(submission)

    with translation.override(language):
        labels = {
            "title": _("Certificate of Participation"),
            "presented": _("This certificate is proudly presented to"),
            "represented": _("Represented by %(representative)s") % {
                "representative": submission.badge_display_name,
            },
            "statement": (
                _("for institutional participation in %(event_name)s with verified attendance.")
                if institution_certificate
                else _(
                    "for participating in %(event_name)s and completing verified attendance."
                )
            ) % {"event_name": event_name},
            "verified": _("Attendance verified"),
            "event_date": _("Event date"),
            "number": _("Certificate number"),
            "scan": _("Scan to verify this certificate"),
        }

    width, height = 1684, 1191
    image = Image.new("RGB", (width, height), "#fbfaf4")
    draw = ImageDraw.Draw(image)
    navy = "#173c59"
    gold = "#aa7c24"
    teal = "#1b7085"

    draw.rectangle((32, 32, width - 32, height - 32), outline=gold, width=8)
    draw.rectangle((50, 50, width - 50, height - 50), outline=navy, width=3)
    draw.line((75, 75, 220, 75), fill=teal, width=12)
    draw.line((75, 75, 75, 220), fill=teal, width=12)
    draw.line((width - 75, height - 75, width - 220, height - 75), fill=teal, width=12)
    draw.line((width - 75, height - 75, width - 75, height - 220), fill=teal, width=12)

    def centered(text, y, font, fill=navy):
        box = draw.textbbox((0, 0), text, font=font)
        x = (width - (box[2] - box[0])) / 2
        draw.text((x, y), text, font=font, fill=fill)

    def centered_fitted(text, y, size, max_width, fill=navy, min_size=28):
        font = _certificate_font(size, bold=True)
        while size > min_size:
            box = draw.textbbox((0, 0), text, font=font)
            if box[2] - box[0] <= max_width:
                break
            size -= 2
            font = _certificate_font(size, bold=True)
        centered(text, y, font, fill)

    centered(event.code, 105, _certificate_font(28, bold=True), gold)
    centered(event_name, 155, _certificate_font(42, bold=True))
    centered(labels["title"], 265, _certificate_font(56, bold=True), gold)
    centered(labels["presented"], 370, _certificate_font(28), navy)
    recipient_font_size = 58 if institution_certificate else 68
    centered_fitted(recipient_name, 430, recipient_font_size, width - 300, navy)
    draw.line((350, 525, width - 350, 525), fill=gold, width=3)

    if institution_certificate:
        centered(
            labels["represented"],
            550,
            _certificate_font(27, bold=True),
            teal,
        )
    elif submission.badge_organization:
        centered(
            submission.badge_organization,
            550,
            _certificate_font(30, bold=True),
            teal,
        )

    centered(labels["statement"], 630, _certificate_font(27), navy)

    checked_at = timezone.localtime(submission.check_in.checked_in_at)
    draw.text(
        (135, 870),
        labels["event_date"],
        font=_certificate_font(20),
        fill="#607284",
    )
    draw.text(
        (135, 905),
        formatted_event_dates,
        font=_certificate_font(25, bold=True),
        fill=navy,
    )
    draw.text(
        (135, 985),
        labels["number"],
        font=_certificate_font(20),
        fill="#607284",
    )
    draw.text(
        (135, 1020),
        short_certificate_number,
        font=_certificate_font(23, bold=True),
        fill=navy,
    )

    qr_image = Image.open(BytesIO(generate_qr_png(
        verification_url,
        logo_path=certificate_qr_logo_path(event),
    ))).convert("RGB")
    qr_image = qr_image.resize((210, 210))
    image.paste(qr_image, (width - 355, 830))
    qr_label = labels["scan"]
    box = draw.textbbox((0, 0), qr_label, font=_certificate_font(18))
    draw.text(
        (width - 250 - (box[2] - box[0]) / 2, 1050),
        qr_label,
        font=_certificate_font(18),
        fill=navy,
    )

    output = BytesIO()
    image.save(output, format="PDF", resolution=150)
    return output.getvalue()


def safe_spreadsheet_value(value):
    if value is None:
        return ""

    text = str(value)

    if text.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{text}"

    return text


def answer_export_value(answer):
    selected_options = list(answer.selected_options.all())

    if selected_options:
        labels = [
            option.label_en
            if answer.submission.language == "en"
            else option.label_sw
            for option in selected_options
        ]
        return ", ".join(labels)

    if answer.uploaded_file:
        return answer.uploaded_file.url

    if answer.boolean_value is not None:
        if answer.submission.language == "en":
            return "Yes" if answer.boolean_value else "No"
        return "Ndiyo" if answer.boolean_value else "Hapana"

    for value in (
        answer.text_value,
        answer.number_value,
        answer.date_value,
        answer.datetime_value,
    ):
        if value not in (None, ""):
            return value

    return ""


def submissions_csv(submissions):
    submissions = list(submissions)
    form_ids = {item.event_form_id for item in submissions}
    questions = list(
        FormQuestion.objects.filter(
            section__event_form_id__in=form_ids,
        )
        .select_related("section__event_form__event")
        .order_by(
            "section__event_form_id",
            "section__display_order",
            "display_order",
            "id",
        )
    )

    output = StringIO()
    writer = csv.writer(output)
    fixed_headers = [
        "Reference Number",
        "Event",
        "Form",
        "Email",
        "Phone",
        "Language",
        "Complete",
        "Review Status",
        "Reviewed By",
        "Reviewed On",
        "Internal Review Notes",
        "Submitted On",
    ]
    question_headers = [
        f"{question.section.event_form.event.code} — {question.label_en}"
        for question in questions
    ]
    writer.writerow(fixed_headers + question_headers)

    for submission in submissions:
        answer_map = {
            answer.question_id: answer_export_value(answer)
            for answer in submission.answers.all()
        }
        submitted_on = timezone.localtime(submission.created_at).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        reviewed_on = (
            timezone.localtime(submission.reviewed_at).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            if submission.reviewed_at
            else ""
        )
        fixed_values = [
            submission.reference_number,
            submission.event_form.event.code,
            submission.event_form.name_en,
            submission.submitter_email,
            submission.submitter_phone,
            submission.language,
            "Yes" if submission.is_complete else "No",
            submission.get_review_status_display(),
            str(submission.reviewed_by or ""),
            reviewed_on,
            submission.review_notes,
            submitted_on,
        ]
        question_values = [
            answer_map.get(question.id, "")
            if question.section.event_form_id == submission.event_form_id
            else ""
            for question in questions
        ]
        writer.writerow(
            [safe_spreadsheet_value(value) for value in fixed_values + question_values]
        )

    return output.getvalue()
