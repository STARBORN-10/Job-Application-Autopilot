"""
Job exports: CSV, Excel (.xlsx) and PDF.

- Filters (status, minimum score, source, decision) are applied in filter_jobs(), the same way the
  Job Listings page filters, so an export matches what the user is looking at.
- CSV: spreadsheet formula injection is neutralised (cells starting with = + - @ get a leading ').
- Excel: every value is written as a plain string or number cell, never as a formula, so a title such
  as "=HYPERLINK(...)" stays text. Bold header, frozen first row, sensible column widths, autofilter.
- PDF: landscape A4 table report with a title, the export date and the filters used; long text wraps.
"""
import datetime
import io
import json
from typing import Any, Iterable, Optional

from services.analytics import jobs_to_csv

FORMATS = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
}

XLSX_COLUMNS = [
    ("id", "ID", 7), ("title", "Title", 40), ("company", "Company", 24), ("location", "Location", 22),
    ("job_type", "Type", 12), ("experience", "Experience", 14), ("source", "Source", 13),
    ("also_found_on", "Also found on", 18), ("score", "Score", 8), ("status", "Status", 12),
    ("approval_status", "Decision", 11), ("date_found", "Found", 18), ("url", "Link", 45),
    ("match_reason", "Why it matches", 70),
]
PDF_COLUMNS = [("title", "Title", 0.24), ("company", "Company", 0.15), ("location", "Location", 0.14),
               ("source", "Source", 0.09), ("score", "Score", 0.06), ("status", "Status", 0.08),
               ("approval_status", "Decision", 0.08), ("date_found", "Found", 0.08), ("url", "Link", 0.08)]


def _source_names(job) -> list[str]:
    raw = getattr(job, "source_names", None)
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        value = []
    return value if isinstance(value, list) else []


def filter_jobs(jobs: Iterable[Any], status: Optional[str] = None, min_score: Optional[float] = None,
                source: Optional[str] = None, approval_status: Optional[str] = None) -> list:
    """Same semantics as the Job Listings filters. `source` matches the primary source or any merged one."""
    out = []
    src = (source or "").strip().lower()
    for j in jobs:
        if status and (j.status or "To Apply") != status:
            continue
        if min_score is not None and (j.score is None or j.score < min_score):
            continue
        if approval_status and (j.approval_status or "pending") != approval_status:
            continue
        if src:
            names = {(j.source or "unknown").lower(), *(n.lower() for n in _source_names(j))}
            if src not in names:
                continue
        out.append(j)
    return out


def _value(job, key: str) -> Any:
    if key == "also_found_on":
        primary = (job.source or "").lower()
        return ", ".join(n for n in _source_names(job) if n.lower() != primary)
    value = getattr(job, key, None)
    if key == "approval_status":
        value = value or "pending"
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return value


def to_csv(jobs: Iterable[Any]) -> bytes:
    return jobs_to_csv(jobs).encode("utf-8")


def to_xlsx(jobs: Iterable[Any]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Jobs"
    ws.append([label for _key, label, _w in XLSX_COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4F46E5")
        cell.alignment = Alignment(vertical="center")
    for row_idx, job in enumerate(jobs, start=2):
        for col_idx, (key, _label, _w) in enumerate(XLSX_COLUMNS, start=1):
            value = _value(job, key)
            cell = ws.cell(row=row_idx, column=col_idx)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cell.value = value
            else:
                cell.value = "" if value is None else str(value)
                # Force a text cell: openpyxl would otherwise store "=..." as a formula (formula injection).
                cell.data_type = "s"
            if key in ("match_reason", "title"):
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            if key == "url" and value:
                cell.hyperlink = str(value) if str(value).startswith(("http://", "https://")) else None
    for idx, (_key, _label, width) in enumerate(XLSX_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_pdf(jobs: Iterable[Any], filters_text: str = "") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle
    from xml.sax.saxutils import escape

    jobs = list(jobs)
    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title="Job export", author="Job Application Autopilot")
    styles = getSampleStyleSheet()
    cell = ParagraphStyle("cell", parent=styles["BodyText"], fontSize=7.5, leading=9)
    head = ParagraphStyle("head", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
    story = [
        Paragraph("Job Application Autopilot: jobs export", styles["Title"]),
        Paragraph(escape(f"Exported {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} · {len(jobs)} job(s)"
                         + (f" · Filters: {filters_text}" if filters_text else "")), styles["Normal"]),
        Spacer(1, 6 * mm),
    ]
    width = page[0] - 24 * mm
    data = [[Paragraph(label, head) for _k, label, _w in PDF_COLUMNS]]
    for job in jobs:
        row = []
        for key, _label, _w in PDF_COLUMNS:
            value = _value(job, key)
            if key == "score" and isinstance(value, (int, float)):
                text = f"{value:.1f}"
            elif key == "url" and value:
                text = f'<link href="{escape(str(value))}" color="blue">open</link>'
                row.append(Paragraph(text, cell))
                continue
            else:
                text = "" if value is None else str(value)
            row.append(Paragraph(escape(text[:400]), cell))
        data.append(row)
    if len(data) == 1:
        data.append([Paragraph("No jobs match these filters.", cell)] + [""] * (len(PDF_COLUMNS) - 1))
    table = LongTable(data, colWidths=[width * w for _k, _l, w in PDF_COLUMNS], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F46E5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    doc.build(story)
    return buf.getvalue()


def render(fmt: str, jobs: list, filters_text: str = "") -> bytes:
    if fmt == "csv":
        return to_csv(jobs)
    if fmt == "xlsx":
        return to_xlsx(jobs)
    if fmt == "pdf":
        return to_pdf(jobs, filters_text)
    raise ValueError(f"unknown export format '{fmt}'")
