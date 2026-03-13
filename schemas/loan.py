from datetime import date

from pydantic import BaseModel, field_validator
from typing import List, Literal, Optional

class GoldItem(BaseModel):
    gold_type: Literal["new", "old"]
    item_type: str
    purity: Literal["24k", "22k", "18k"]
    gross_weight: float
    net_weight: float

    @field_validator("net_weight")
    def check_weight(cls, net_weight, info):
        gross_weight = info.data.get("gross_weight")

        if gross_weight is not None and net_weight > gross_weight:
            raise ValueError("Net weight must be less than or equal to gross weight")

        return net_weight
    
class LoanCreate(BaseModel):
    customer_id: str
    scheme_id: str
    loan_no: str
    loan_amount: float
    loan_date: date
    gold_packet_no: str
    image:str
    items: List[GoldItem]


class LoanUpdate(BaseModel):
    scheme_id:Optional[str]
    
    loan_amount:Optional[float]
    loan_date:Optional[date]
    
    image:Optional[str]
    items: Optional[List[GoldItem]] 

class GoldItem(BaseModel):
    gold_type: Optional[Literal["new", "old"]]
    item_type: Optional[str]
    purity: Optional[Literal["24k", "22k", "18k"]]
    gross_weight: Optional[float]
    net_weight: Optional[float]   

    @field_validator("net_weight")
    def check_weight(cls, net_weight, info):
        gross_weight = info.data.get("gross_weight")

        if gross_weight is not None and net_weight > gross_weight:
            raise ValueError("Net weight must be less than or equal to gross weight")

        return net_weight

