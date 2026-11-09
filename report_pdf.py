"""Printable PDF screening report."""
from __future__ import annotations

from datetime import date

from fpdf import FPDF, FontFace

TEAL = (15, 118, 110)
LEVEL_COLOR = {"high": (220, 38, 38), "medium": (217, 119, 6), "low": (37, 99, 235)}
VERDICT_COLOR = {"ACTION REQUIRED": (220, 38, 38), "REVIEW": (217, 119, 6), "NO FLAGS": (22, 163, 74)}
LEVEL_LABEL = {"high": "HIGH", "medium": "MEDIUM", "low": "INFO"}


def _t(s) -> str:
    """Make text safe for the built-in PDF fonts."""
    s = str(s if s is not None else "")
    for a, b in {"≤": "<=", "≥": ">=", "–": "-", "—": "-", "’": "'", "‘": "'",
                 "“": '"', "”": '"', "•": "-", "µ": "u"}.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def build_pdf(report, ghs: dict, file_name: str) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_margins(15, 15, 15)
    w = pdf.epw

    # Header
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*TEAL)
    pdf.cell(w, 9, "SDS & REACH Screening Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(w, 5, _t(f"Checked on {date.today():%d %b %Y}  |  File: {file_name}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(w, 5, _t(f"Reference: {report.svhc_source}; UN GHS hazard statements"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Verdict box
    color = VERDICT_COLOR[report.verdict]
    pdf.set_fill_color(*color)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(w, 10, _t(f"  {report.verdict}"), fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "", 10)
    n_svhc = sum(1 for c in report.components if c.svhc)
    pdf.multi_cell(w, 6, _t(
        f"Product: {report.product_name}\n"
        f"Signal word: {report.signal_word or 'not found'}   |   Substances: {len(report.components)}   |   "
        f"SVHCs: {n_svhc}   |   Section 2 hazard codes: {', '.join(report.section2_hcodes) or 'none'}"), align="L")
    pdf.ln(3)

    def table_style():
        pdf.set_fill_color(255, 255, 255)
        pdf.set_draw_color(209, 213, 219)
        pdf.set_text_color(20, 20, 20)

    head_style = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=TEAL)

    def heading(text):
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*TEAL)
        pdf.cell(w, 7, _t(text), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(20, 20, 20)

    # Findings
    heading("Findings")
    if not report.issues:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(w, 6, "No issues found against the loaded reference data.", new_x="LMARGIN", new_y="NEXT")
    for i in report.issues:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*LEVEL_COLOR[i["level"]])
        pdf.cell(18, 5.5, LEVEL_LABEL[i["level"]])
        pdf.set_text_color(20, 20, 20)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(w - 18, 5.5, _t(f"{i['type']}: {i['detail']}"), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    # Composition
    heading("Composition (Section 3)")
    pdf.set_font("Helvetica", "", 8.5)
    table_style()
    with pdf.table(col_widths=(42, 18, 18, 12, 50), line_height=5, text_align="LEFT",
                   headings_style=head_style, first_row_as_headings=True) as table:
        head = table.row()
        for h in ("Substance", "CAS", "Conc.", "SVHC", "Hazard codes"):
            head.cell(h)
        for c in report.components:
            r = table.row()
            r.cell(_t(c.name))
            r.cell(_t(c.cas + ("" if c.cas_valid else " (invalid)")))
            r.cell(_t(c.concentration or "not stated"))
            r.cell("YES" if c.svhc else "No",
                   style=FontFace(emphasis="BOLD", color=(220, 38, 38)) if c.svhc else None)
            r.cell(_t(", ".join(c.hcodes) or "-"))

    # Hazard statements
    codes = sorted(set(report.section2_hcodes) | {h for c in report.components for h in c.hcodes})
    if codes:
        heading("Hazard statements")
        pdf.set_font("Helvetica", "", 8.5)
        table_style()
        with pdf.table(col_widths=(16, 84, 40), line_height=5, text_align="LEFT",
                       headings_style=head_style, first_row_as_headings=True) as table:
            head = table.row()
            for h in ("Code", "Statement", "Hazard class"):
                head.cell(h)
            for h in codes:
                g = ghs.get(h) or ghs.get(h[:4]) or {}
                r = table.row()
                r.cell(h)
                r.cell(_t(g.get("statement", "Unknown code")))
                r.cell(_t(g.get("hazard_class", "")))

    # Footer note
    pdf.ln(5)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(w, 4.5, _t(
        "Screening aid based on public reference data (ECHA Candidate List; UN GHS hazard statements via "
        "PubChem). Not a regulatory determination. Results depend on the text that could be read from the SDS. "
        "Generated by SDS & REACH Checker, built by Dilrusha Abdul Majeed."), align="L")
    return bytes(pdf.output())
