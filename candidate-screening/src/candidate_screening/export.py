"""Bounded, recruiter-authorized screening result workbooks."""

from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field, model_validator

from .summary_labels import OUTCOME_LABELS, readable_summary


class ExportRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_ids(self) -> "ExportRequest":
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("candidate IDs must be unique")
        return self


HEADERS = (
    "Candidate ID",
    "Name",
    "Email",
    "Phone",
    "Current organization",
    "Location",
    "Education",
    "Skills",
    "Current CTC",
    "Screening status",
    "Outcome",
    "Candidate-reported",
    "Missing answers",
    "Recruiter follow-up",
    "Interest",
    "Earliest start date",
    "Notice period (days)",
    "Expected salary min",
    "Expected salary max",
    "Currency",
    "Pay period",
    "Negotiable",
    "Completed at (UTC)",
)


def _literal(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def build_workbook(rows: list[dict[str, Any]]) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Screening results"
    sheet.append(HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2458D3")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet.row_dimensions[1].height = 32
    for row in rows:
        reported, missing, follow_up = readable_summary(
            row["confirmed"], row["missing"], row["needs_verification"],
            row.get("question_labels", {}),
        )
        sheet.append(
            [
                _literal(row["candidate_id"]),
                None,
                _literal(row["recipient_email"]),
                None,
                None,
                None,
                None,
                None,
                None,
                row["status"].capitalize(),
                OUTCOME_LABELS[row["outcome"]],
                _literal("\n".join(reported)),
                _literal("\n".join(missing)),
                _literal("\n".join(follow_up)),
                row["interest"].replace("_", " ").capitalize() if row["interest"] else None,
                row["earliest_start_date"],
                row["notice_days"],
                row["salary_minimum"],
                row["salary_maximum"],
                row["salary_currency"],
                row["salary_period"],
                row["salary_negotiable"],
                row["completed_at"].isoformat(),
            ]
        )
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{sheet.max_row}"
    for index, header in enumerate(HEADERS, 1):
        letter = get_column_letter(index)
        sheet.column_dimensions[letter].width = min(30, max(17, len(header) + 3))
    sheet.column_dimensions["C"].width = 36
    for letter in ("L", "M", "N"):
        sheet.column_dimensions[letter].width = 60
    for cells, row in zip(sheet.iter_rows(min_row=2), rows, strict=True):
        for cell in cells:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        summary_lines = max(
            len(row["confirmed"]), len(row["missing"]), len(row["needs_verification"]), 1
        )
        sheet.row_dimensions[cells[0].row].height = min(330, max(42, 27 * summary_lines))
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()
