from datetime import date
from pydantic import BaseModel, computed_field
from typing import List, Literal, Optional


class GoldItem(BaseModel):
    gold_type: Literal["new", "old"]
    item_type: str
    purity: Literal["24k", "22k", "18k"]

    gross_weight: float
    stone_weight: float = 0
    dust_weight: float = 0
    wax_weight: float = 0

    @computed_field
    @property
    def net_weight(self) -> float:
        return self.gross_weight - (
            self.stone_weight +
            self.dust_weight +
            self.wax_weight
        )


class LoanCreate(BaseModel):
    
    scheme_id: str
    loan_no: str
    loan_amount: float
    loan_date: date
    gold_packet_no: str
    image: str
    items: List[GoldItem]


class GoldItemUpdate(BaseModel):
    gold_type: Optional[Literal["new", "old"]]
    item_type: Optional[str]
    purity: Optional[Literal["24k", "22k", "18k"]]

    gross_weight: Optional[float]
    stone_weight: Optional[float]
    dust_weight: Optional[float]
    wax_weight: Optional[float]


class LoanUpdate(BaseModel):
    scheme_id: Optional[str]
    loan_amount: Optional[float]
    loan_date: Optional[date]
    image: Optional[str]
    items: Optional[List[GoldItemUpdate]]