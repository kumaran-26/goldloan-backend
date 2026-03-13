from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from datetime import datetime

from schemas.loan import LoanCreate, LoanUpdate
from database.db import (
    customers_collection,
    scheme_collection,
    gold_rates_loans_collection,
    loans_collection
)
from utils.auth import admin_or_staff_required, admin_required

router = APIRouter(prefix="/loans-api", tags=["loans"])


@router.post("/loan/create")
def create_loan(data: LoanCreate, user=Depends(admin_or_staff_required)):

    # Get customer
    customer = customers_collection.find_one(
        {"_id": ObjectId(data.customer_id)}
    )

    # Get scheme
    scheme = scheme_collection.find_one(
        {"_id": ObjectId(data.scheme_id)}
    )

    if not customer or customer["status"] != "active":
        raise HTTPException(status_code=404, detail="Customer not found")

    if not scheme or scheme["status"] != "active":
        raise HTTPException(status_code=404, detail="Scheme not found")

    total_eligible = 0
    total_net_weight = 0
    items_data = []

    # Loop through gold items
    for item in data.items:

        rate = gold_rates_loans_collection.find_one(
            {"carat": item.purity.lower()}
        )

        if not rate:
            raise HTTPException(
                status_code=400,
                detail=f"Gold rate not found for {item.purity}"
            )

        eligible_per_gram = rate["eligible_loan_per_gram"]

        eligible_value = item.net_weight * eligible_per_gram

        total_eligible += eligible_value
        total_net_weight += item.net_weight

        items_data.append({
            "gold_type": item.gold_type,
            "item_type": item.item_type,
            "purity": item.purity,
            "gross_weight": item.gross_weight,
            "net_weight": item.net_weight,
            "eligible_value": eligible_value
        })

    # Validate loan amount
    if data.loan_amount > total_eligible:
        raise HTTPException(
            status_code=400,
            detail="Loan amount exceeds eligible value"
        )

    # Status logic
    status = "approved" if user["role"] == "admin" else "pending"

    loan_doc = {
        "loan_no": data.loan_no,   # removed ()
        "gold_packet_no": data.gold_packet_no,
        "image": data.image,
        "customer_id": customer["_id"],
        "customer_code": customer["customer_code"],
        "customer_name": customer["firstname"] + " " + customer["lastname"],
        "scheme_id": scheme["_id"],
        "scheme_name": scheme["scheme_name"],
        "loan_amount": data.loan_amount,
        "loan_date": datetime.utcnow(),
        "total_eligible_amount": total_eligible,
        "total_net_weight": total_net_weight,
        "items": items_data,
        "status": status,
        "created_by": user["role"],
        "created_at": datetime.utcnow()
    }

    result = loans_collection.insert_one(loan_doc)

    return {
        "loan_id": str(result.inserted_id),
        "customer_code": customer["customer_code"],
        "customer_name": customer["firstname"] + " " + customer["lastname"],
        "customer_id": str(customer["_id"]),
        "scheme_id": str(scheme["_id"]),
        "scheme_name": scheme["scheme_name"],
        "loan_no": loan_doc["loan_no"],
        "gold_packet_no": data.gold_packet_no,
        "loan_amount": data.loan_amount,
        "total_eligible_amount": total_eligible,
        "total_net_weight": total_net_weight,
        "items": items_data,
        "status": status
    }

@router.put("/loan/updateapproval/{id}") 
def update_loan_approval(id: str, user=Depends(admin_required)):

    loan = loans_collection.find_one({"_id": ObjectId(id)})

    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if loan["status"] != "pending":
        raise HTTPException(status_code=400, detail="Only pending loans can be updated")

    new_status = "approved" if user["role"] == "admin" else "rejected"

    loans_collection.update_one(
        {"_id": ObjectId(id)},
        {
            "$set": {
                "status": new_status,
                "updated_at": datetime.utcnow()
            }
        }
    )

    return {"message": f"Loan {new_status}"}   

@router.put("/loan/update/{id}")
def update_loan(id: str, data: LoanUpdate, user=Depends(admin_required)):

    loan = loans_collection.find_one({"_id": ObjectId(id)})

    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if loan["status"] != "pending":
        raise HTTPException(status_code=400, detail="Only pending loans can be updated")

    update_doc = {}

    # Update scheme
    if data.scheme_id:
        scheme = scheme_collection.find_one({"_id": ObjectId(data.scheme_id)})

        if not scheme:
            raise HTTPException(status_code=404, detail="Scheme not found")

        update_doc["scheme_id"] = scheme["_id"]
        update_doc["scheme_name"] = scheme["scheme_name"]

    # Update basic fields
  

    if data.loan_date:
        update_doc["loan_date"] = data.loan_date

    if data.image:
        update_doc["image"] = data.image

    # Update gold items
    if data.items:

        total_eligible = 0
        total_net_weight = 0
        items_data = []

        for item in data.items:

            rate = gold_rates_loans_collection.find_one(
                {"carat": item.purity.lower()}
            )

            if not rate:
                raise HTTPException(
                    status_code=400,
                    detail=f"Gold rate not found for {item.purity}"
                )

            eligible_per_gram = rate["eligible_loan_per_gram"]

            eligible_value = item.net_weight * eligible_per_gram

            total_eligible += eligible_value
            total_net_weight += item.net_weight

            items_data.append({
                "gold_type": item.gold_type,
                "item_type": item.item_type,
                "purity": item.purity,
                "gross_weight": item.gross_weight,
                "net_weight": item.net_weight,
                "eligible_value": eligible_value
            })

        update_doc["items"] = items_data
        update_doc["total_eligible_amount"] = total_eligible
        update_doc["total_net_weight"] = total_net_weight

        # Validate loan amount if provided
        if data.loan_amount and data.loan_amount > total_eligible:
            raise HTTPException(
                status_code=400,
                detail="Loan amount exceeds eligible value"
            )

    # Update loan amount
    if data.loan_amount:
        update_doc["loan_amount"] = data.loan_amount

    update_doc["updated_at"] = datetime.utcnow()

    loans_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": update_doc}
    )

    updated_loan = loans_collection.find_one({"_id": ObjectId(id)})

    # Convert ObjectId to string
    updated_loan["id"] = str(updated_loan["_id"])
    updated_loan["customer_id"] = str(updated_loan["customer_id"])
    updated_loan["scheme_id"] = str(updated_loan["scheme_id"])

    del updated_loan["_id"]

    return updated_loan