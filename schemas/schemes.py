
from typing import Optional, Literal

from pydantic import BaseModel, Field
from datetime import datetime


class SchemeSchema(BaseModel):

    scheme_name: str

    tenure_months: int = Field(..., gt=0, le=12)

    interest_rate: float = Field(..., gt=0)

    penalty_percent: float = Field(..., ge=2)

    minimum_loan_duedate: int = Field(..., gt=0, le=10)

    total_tenure_months: int = Field(..., gt=0, le=36)

    Repayment_type: Literal["bullet", "emi"]


class SchemeResponse(SchemeSchema):

    id: int
    status: str = "active"

    created_at: datetime = datetime.utcnow()
    updated_at: datetime = datetime.utcnow()


class SchemeUpdate(BaseModel):

    scheme_name: Optional[str] = None

    tenure_months: Optional[int] = Field(None, gt=0, le=36)

    interest_rate: Optional[float] = Field(None, gt=0)

    penalty_percent: Optional[float] = Field(None, ge=0)

    total_tenure_months: Optional[int] = Field(None, gt=0, le=36)

    minimum_loan_duedate: Optional[int] = Field(None, gt=0, le=10)

    Repayment_type: Optional[Literal["bullet", "emi"]] = None

    status: Optional[str] = None


class SchemeStatusUpdate(BaseModel):

    status: str

    updated_at: datetime = datetime.utcnow()