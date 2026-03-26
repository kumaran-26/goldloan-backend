from fastapi import APIRouter, Depends
from datetime import datetime
from bson import ObjectId
from database.db import gold_rates_loans_collection 
from database.db import historygoldrateloans_collection
from schemas.gold_rate import GoldLoanSchema, GoldLoanUpdate
from utils.auth import admin_required


router = APIRouter(prefix="/goldratesloans", tags=["gold-rates-loans"])


@router.post("/goldloan_create")
def create_goldloan(data: GoldLoanSchema, user=Depends(admin_required)):

    goldloan_dict = data.dict()

    # calculate eligible loan amount
    goldloan_dict["eligible_loan_per_gram"] = (
        goldloan_dict["gold_rate"] * (goldloan_dict["ltv"] / 100)
    )

    
    goldloan_dict["created_at"] = datetime.utcnow()
    

    gold_rates_loans_collection.insert_one(goldloan_dict)

    # store history also
    historygoldrateloans_collection.insert_one(goldloan_dict.copy())

    return {"message": "Gold loan configuration created successfully"}




@router.put("/goldloan/update/{id}")
def update_goldloan(id: str, data: GoldLoanUpdate, user=Depends(admin_required)):

    existing = gold_rates_loans_collection.find_one({"_id": ObjectId(id)})

    if not existing:
        return {"message": "Gold loan record not found"}

    update_data = {k: v for k, v in data.dict().items() if v is not None}

    gold_rate = update_data.get("gold_rate", existing["gold_rate"])
    ltv = update_data.get("ltv", existing["ltv"])

    # recalculate loan amount
    update_data["eligible_loan_per_gram"] = gold_rate * (ltv / 100)

    update_data["updated_at"] = datetime.utcnow()

    gold_rates_loans_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": update_data}
    )

    # store history (insert new record)
    history_record = existing.copy()
    history_record.update(update_data)
    
    history_record.pop("_id", None)

    historygoldrateloans_collection.insert_one(history_record)

    return {"message": "Gold loan updated successfully"}

@router.get("/goldloans/history")
def get_goldloan_history(user=Depends(admin_required)):     
    history = list(historygoldrateloans_collection.find())

    for record in history:
        record["id"] = str(record["_id"])
        del record["_id"]

    return history

@router.get("/goldloans/allcarats")
def get_goldloan(user=Depends(admin_required)):     
    carats = list(gold_rates_loans_collection.find())

    for carat in carats:
        carat["id"] = str(carat["_id"])
        del carat["_id"]

    return carats



