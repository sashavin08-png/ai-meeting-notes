"""
PDF export for a meeting's notes — summary, action items, and full transcript.
"""

from fpdf import FPDF
from fpdf.enums import XPos, YPos


def _sanitize(text: str) -> str:
    """fpdf2's default font (Helvetica) only supports Latin-1 characters.
    Non-Latin text (e.g. Cyrillic) needs a Unicode font — see generate_pdf()."""
    return text or ""


def generate_pdf(meeting: dict) -> bytes:
    pdf = FPDF()
    pdf.add_page()

    # Try to use a Unicode-capable font if one is available, so transcripts
    # in Russian/Ukrainian/etc. render correctly instead of raising an error
    # or dropping characters. Falls back to the built-in Latin-only font
    # for environments where no Unicode TTF is installed.
    unicode_font_loaded = False
    for font_path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        try:
            pdf.add_font("Body", "", font_path)
            pdf.set_font("Body", size=11)
            unicode_font_loaded = True
            break
        except (RuntimeError, FileNotFoundError):
            continue

    if not unicode_font_loaded:
        pdf.set_font("Helvetica", size=11)

    def heading(text):
        pdf.set_font_size(16)
        pdf.multi_cell(0, 10, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font_size(11)
        pdf.ln(2)

    def label(text):
        pdf.set_font_size(10)
        pdf.multi_cell(0, 8, text.upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font_size(11)

    def body(text):
        pdf.multi_cell(0, 6, _sanitize(text) or "(none)", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(4)

    heading(meeting["title"])
    label(f"Date: {meeting['created_at'][:16]}")
    pdf.ln(4)

    label("Summary")
    body(meeting["summary"])

    label("Action Items")
    body(meeting["action_items"])

    label("Full Transcript")
    body(meeting["transcript"])

    return bytes(pdf.output())
