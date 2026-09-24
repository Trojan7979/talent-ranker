from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

AnswerStatus = Literal["answered", "unsure", "prefer_not_to_answer"]
Confirmation = Literal["yes", "no", "unsure"]
Interest = Literal["interested", "not_interested", "needs_details", "unsure"]
PayPeriod = Literal["hour", "month", "year"]


class MustHave(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=500)
    hard_fail_on_no: bool = False


class JobQuestions(BaseModel):
    version: int = Field(ge=1)
    must_haves: list[MustHave] = Field(default_factory=list, max_length=30)
    require_interest: bool = True
    require_availability: bool = True
    require_notice_period: bool = True
    require_salary: bool = True
    max_notice_days: int | None = Field(default=None, ge=0, le=365)
    target_start_date: date | None = None
    salary_maximum: Decimal | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    salary_period: PayPeriod | None = None

    @model_validator(mode="after")
    def validate_config(self) -> "JobQuestions":
        ids = [item.id for item in self.must_haves]
        if len(ids) != len(set(ids)):
            raise ValueError("must-have IDs must be unique")
        salary_parts = (self.salary_maximum, self.salary_currency, self.salary_period)
        if any(part is not None for part in salary_parts) and not all(
            part is not None for part in salary_parts
        ):
            raise ValueError("salary comparison needs maximum, currency, and period")
        return self


class QualificationAnswer(BaseModel):
    requirement_id: str = Field(min_length=1)
    confirmation: Confirmation


class AvailabilityAnswer(BaseModel):
    status: AnswerStatus
    earliest_start_date: date | None = None

    @model_validator(mode="after")
    def validate_date(self) -> "AvailabilityAnswer":
        if (self.status == "answered") != (self.earliest_start_date is not None):
            raise ValueError(
                "answered availability needs a date; uncertain availability cannot set one"
            )
        return self


class NoticeAnswer(BaseModel):
    status: AnswerStatus
    days: int | None = Field(default=None, ge=0, le=365)

    @model_validator(mode="after")
    def validate_days(self) -> "NoticeAnswer":
        if (self.status == "answered") != (self.days is not None):
            raise ValueError("answered notice needs days; uncertain notice cannot set days")
        return self


class SalaryAnswer(BaseModel):
    status: AnswerStatus
    minimum: Decimal | None = Field(default=None, ge=0)
    maximum: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    period: PayPeriod | None = None
    negotiable: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> "SalaryAnswer":
        values = (self.minimum, self.maximum, self.currency, self.period)
        if self.status == "answered":
            if any(value is None for value in values):
                raise ValueError("answered salary needs range, currency, and period")
            if self.minimum > self.maximum:
                raise ValueError("salary minimum cannot exceed maximum")
        elif any(value is not None for value in values):
            raise ValueError("uncertain salary cannot include a range")
        return self


class ScreeningAnswers(BaseModel):
    qualifications: list[QualificationAnswer] = Field(default_factory=list, max_length=30)
    interest: Interest | None = None
    availability: AvailabilityAnswer | None = None
    notice_period: NoticeAnswer | None = None
    salary: SalaryAnswer | None = None

    @model_validator(mode="after")
    def validate_qualifications(self) -> "ScreeningAnswers":
        ids = [item.requirement_id for item in self.qualifications]
        if len(ids) != len(set(ids)):
            raise ValueError("qualification requirement IDs must be unique")
        return self
