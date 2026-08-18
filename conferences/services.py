from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from django.conf import settings
from django.utils import timezone


def _font(size, bold=False):
    names = (
        ("DejaVuSans-Bold.ttf", "Arial Bold.ttf")
        if bold
        else ("DejaVuSans.ttf", "Arial.ttf")
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrapped_lines(draw, text, font, max_width):
    words = str(text or "").split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def _load_event_logo(event):
    try:
        if event.logo:
            event.logo.open("rb")
            return Image.open(event.logo).convert("RGBA")
    except (OSError, ValueError):
        pass

    fallback = Path(settings.BASE_DIR) / "static" / "images" / "ministry-of-education-logo.png"
    return Image.open(fallback).convert("RGBA")


def generate_programme_pdf(event, sessions):
    page_width, page_height = 1240, 1754
    navy = "#17365d"
    teal = "#087f73"
    muted = "#526579"
    border = "#c9d8e5"
    pages = []
    logo = _load_event_logo(event)
    logo.thumbnail((105, 105))

    for session in sessions:
        page = Image.new("RGB", (page_width, page_height), "white")
        draw = ImageDraw.Draw(page)
        margin = 62
        content_width = page_width - (margin * 2)

        page.paste(logo, (margin, 48), logo)
        text_x = margin + 130
        draw.text((text_x, 48), event.code, font=_font(20, bold=True), fill=teal)
        draw.text((text_x, 76), "CONFERENCE PROGRAMME", font=_font(28, bold=True), fill=navy)
        event_lines = _wrapped_lines(draw, event.title_en, _font(24, bold=True), content_width - 130)
        event_y = 112
        for line in event_lines[:2]:
            draw.text((text_x, event_y), line, font=_font(24, bold=True), fill=navy)
            event_y += 30

        starts = timezone.localtime(event.starts_at).strftime("%d %b %Y")
        ends = timezone.localtime(event.ends_at).strftime("%d %b %Y")
        venue = f" · {event.venue.name}" if event.venue_id else ""
        draw.text((text_x, event_y + 2), f"{starts} – {ends}{venue}", font=_font(17), fill=muted)
        header_bottom = max(175, event_y + 34)
        draw.line((margin, header_bottom, page_width - margin, header_bottom), fill=navy, width=4)

        session_start = timezone.localtime(session.starts_at)
        draw.text(
            (margin, header_bottom + 22),
            session_start.strftime("%A, %d %B %Y").upper(),
            font=_font(18, bold=True),
            fill=teal,
        )
        draw.text((margin, header_bottom + 52), session.title, font=_font(32, bold=True), fill=navy)

        y = header_bottom + 112
        items = list(session.programme_items.all())
        available_height = page_height - y - 60
        row_height = max(155, available_height // max(len(items), 1))

        for item in items:
            start = timezone.localtime(item.starts_at).strftime("%H:%M")
            end = timezone.localtime(item.ends_at).strftime("%H:%M")
            draw.line((margin, y, page_width - margin, y), fill=border, width=2)
            draw.text((margin, y + 18), f"{start}–{end}", font=_font(24, bold=True), fill=navy)

            item_x = margin + 210
            draw.text((item_x, y + 16), item.get_item_type_display().upper(), font=_font(15, bold=True), fill=teal)
            title_lines = _wrapped_lines(draw, item.title, _font(25, bold=True), content_width - 210)
            title_y = y + 42
            for line in title_lines[:2]:
                draw.text((item_x, title_y), line, font=_font(25, bold=True), fill=navy)
                title_y += 31

            if item.description:
                description_lines = _wrapped_lines(draw, item.description, _font(17), content_width - 210)
                for line in description_lines[:2]:
                    draw.text((item_x, title_y + 3), line, font=_font(17), fill=muted)
                    title_y += 23
            if item.venue_name:
                draw.text((item_x, title_y + 5), f"Location: {item.venue_name}", font=_font(17, bold=True), fill=muted)

            y += row_height

        draw.line((margin, min(y, page_height - 48), page_width - margin, min(y, page_height - 48)), fill=border, width=2)
        pages.append(page)

    output = BytesIO()
    pages[0].save(
        output,
        format="PDF",
        resolution=150,
        save_all=True,
        append_images=pages[1:],
    )
    return output.getvalue()

