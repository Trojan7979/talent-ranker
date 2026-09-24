"""Bounded, recruiter-authorized screening result workbooks."""

from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field, model_validator


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
    "Confirmed",
    "Missing",
    "Needs verification",
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
    for row in rows:
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
                row["status"],
                row["outcome"],
                _literal(", ".join(row["confirmed"])),
                _literal(", ".join(row["missing"])),
                _literal(", ".join(row["needs_verification"])),
                row["interest"],
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
    sheet.column_dimensions["A"].width = 20
    sheet.column_dimensions["C"].width = 34
    sheet.column_dimensions["K"].width = 25
    for column in ("L", "M", "N"):
        sheet.column_dimensions[column].width = 35
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()
