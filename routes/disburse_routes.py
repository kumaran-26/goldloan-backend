from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from datetime import datetime
from utils.auth import admin_required
from database.db import (
    loans_collection,
    disbursements_collection
)



router = APIRouter(prefix="/disburse", tags=["Disbursement"])

@router.post("/loan/disburse/{loan_id}")
def disburse_loan(loan_id: str, user=Depends(admin_required)):

    loan = loans_collection.find_one({"_id": ObjectId(loan_id)})

    if not loan:
        return {"error": "Loan not found"}
    
    existing = disbursements_collection.find_one({"loan_id": ObjectId(loan_id)})

    if existing:
      return {"error": "Loan already disbursed"}

    # check loan status
    if loan["status"] != "approved":
        return {"error": "Loan is not eligible for disbursement"}

    disburse_data = {
        "loan_id": loan["_id"],
        "loan_no": loan["loan_no"],
        "customer_id": loan["customer_id"],
        "customer_code": loan["customer_code"],
        "customer_name": loan["customer_name"],
        "disburse_amount": loan["loan_amount"],
        "total_net_weight": loan["total_net_weight"],
        "disburse_date": datetime.utcnow(),
        "status": "completed",
        "created_at": datetime.utcnow()
    }

    # insert disbursement
    disbursements_collection.insert_one(disburse_data)

    # update loan status
    loans_collection.update_one(
        {"_id": ObjectId(loan_id)},
        {
            "$set": {
                "status": "active",
                "loan_start_date": datetime.utcnow()
            }
        }
    )

    return {"message": "Loan disbursed and activated successfully"}