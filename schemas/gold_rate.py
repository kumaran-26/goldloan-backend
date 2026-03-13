from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class GoldLoanSchema(BaseModel):

    carat: Literal["24k", "22k", "18k"]

    

    gold_rate: float = Field(..., gt=0)

    ltv: float = Field(..., gt=0, le=100)




class GoldLoanUpdate(BaseModel):

    carat: Optional[Literal["24k", "22k", "18k"]] = None

    gold_rate: Optional[float] = Field(None, gt=0)

    ltv: Optional[float] = Field(None, gt=0, le=100)

