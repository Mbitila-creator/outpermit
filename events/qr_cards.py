from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from forms_builder.services import generate_qr_png


CARD_WIDTH = 1600
CARD_HEIGHT = 760
TEXT_WIDTH = 1200
TEXT_HEIGHT = 560
QR_ONLY_SIZE = 1000
NAVY = "#17365d"
MUTED = "#64748b"
BORDER = "#b9c7d6"


def _font(size, *, bold=False):
    names = (
        ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf")
        if bold
        else ("DejaVuSans.ttf", "LiberationSans-Regular.ttf")
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap_text(draw, text, font, max_width, max_lines):
    words = str(text or "—").split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    consumed = " ".join(lines)
    original = " ".join(words)
    if consumed != original and lines:
        while lines[-1] and draw.textlength(f"{lines[-1]}…", font=font) > max_width:
            lines[-1] = lines[-1][:-1]
        lines[-1] = f"{lines[-1].rstrip()}…"
    return lines or ["—"]


def _draw_lines(draw, lines, position, font, fill, spacing):
    x, y = position
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += spacing
    return y


def _qr_image(verification_url, size):
    image = Image.open(BytesIO(generate_qr_png(verification_url))).convert("RGB")
    return image.resize((size, size), Image.Resampling.NEAREST)


def _save_png(image):
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _publication_count(participant):
    publications = getattr(participant, "active_publications", None)
    if publications is not None:
        return len(publications)
    return participant.publications.filter(is_active=True).count()


def _draw_participant_text(draw, participant, *, text_x, text_y, text_width):
    event_font = _font(31, bold=True)
    name_font = _font(49, bold=True)
    institution_font = _font(28)
    instruction_font = _font(27)

    publication_count = _publication_count(participant)
    publication_label = "publication" if publication_count == 1 else "publications"
    identity_lines = _wrap_text(
        draw,
        f"{participant.event.code} · {publication_count} {publication_label}",
        event_font,
        text_width,
        1,
    )
    _draw_lines(
        draw,
        identity_lines,
        (text_x, text_y),
        event_font,
        NAVY,
        40,
    )
    name_lines = _wrap_text(
        draw,
        participant.full_name,
        name_font,
        text_width,
        2,
    )
    y = _draw_lines(
        draw,
        name_lines,
        (text_x, text_y + 62),
        name_font,
        "#000000",
        62,
    )
    institution_lines = _wrap_text(
        draw,
        participant.institution,
        institution_font,
        text_width,
        3,
    )
    y = _draw_lines(
        draw,
        institution_lines,
        (text_x, y + 9),
        institution_font,
        "#111111",
        39,
    )
    draw.text(
        (text_x, y + 20),
        "Scan to view the verified researcher record",
        font=instruction_font,
        fill=MUTED,
    )


def render_participant_qr_only(verification_url):
    """Return a high-resolution PNG containing only the scannable QR code."""
    return _save_png(_qr_image(verification_url, QR_ONLY_SIZE))


def render_participant_text_image(participant):
    """Return a PNG containing only the text section of the participant card."""
    image = Image.new("RGB", (TEXT_WIDTH, TEXT_HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    _draw_participant_text(
        draw,
        participant,
        text_x=55,
        text_y=70,
        text_width=TEXT_WIDTH - 110,
    )
    return _save_png(image)


def render_participant_qr_card(participant, verification_url):
    """Return a paste-ready PNG card containing the participant's QR identity."""
    card = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), "white")
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle(
        (3, 3, CARD_WIDTH - 4, CARD_HEIGHT - 4),
        radius=28,
        outline=BORDER,
        width=4,
    )

    card.paste(_qr_image(verification_url, 420), (90, 170))

    text_x = 585
    text_width = CARD_WIDTH - text_x - 80
    _draw_participant_text(
        draw,
        participant,
        text_x=text_x,
        text_y=183,
        text_width=text_width,
    )
    return _save_png(card)
