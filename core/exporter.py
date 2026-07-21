"""
PDF export for a meeting's notes — summary, action items, and full transcript.
"""

from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

# Bundled directly in the project (rather than relying on the OS having a
# Unicode font installed at some guessed system path — that worked in one
# Linux test environment but silently failed on Windows, where no font was
# found at those paths, and fpdf2 fell back to a Latin-only font that can't
# render Cyrillic at all). This file ships from matplotlib's redistributable
# DejaVu Sans font (Bitstream Vera / DejaVu license — free to embed) and
# works identically on any OS since it's just a path relative to this file.
_FONT_PATH = Path(__file__).parent / "fonts" / "DejaVuSans.ttf"


def _sanitize(text: str) -> str:
    return text or ""


def generate_pdf(meeting: dict) -> bytes:
    pdf = FPDF()
    pdf.add_page()

    pdf.add_font("Body", "", str(_FONT_PATH))
    pdf.set_font("Body", size=11)

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
