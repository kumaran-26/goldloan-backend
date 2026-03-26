from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from datetime import datetime

from schemas.loan import LoanCreate, LoanUpdate
from database.db import (
    customers_collection,
    scheme_collection,
    gold_rates_loans_collection,
    loans_collection,
    staffs_collection
)

from utils.auth import admin_or_staff_required, admin_required

router = APIRouter(prefix="/loans-api", tags=["loans"])
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from datetime import datetime

from database.db import (
    loans_collection,
    scheme_collection,
    customers_collection,
    gold_rates_loans_collection,
    staffs_collection
)

from utils.auth import admin_or_staff_required
from schemas.loan import LoanCreate

router = APIRouter(prefix="/loan", tags=["Loan"])


@router.post("/create/{id}")
def create_loan(id: str, data: LoanCreate, user=Depends(admin_or_staff_required)):

    # =====================================================
    # GET CUSTOMER
    # =====================================================
    customer = customers_collection.find_one({"_id": ObjectId(id)})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # =====================================================
    # GET SCHEME
    # =====================================================
    scheme = scheme_collection.find_one({"_id": ObjectId(data.scheme_id)})
    if not scheme or scheme.get("status") != "active":
        raise HTTPException(status_code=404, detail="Scheme not found")

    # =====================================================
    # 🔥 DUPLICATE CHECK (IMPORTANT FIX)
    # =====================================================
    if loans_collection.find_one({"loan_no": data.loan_no}):
        raise HTTPException(status_code=400, detail="Loan number already exists")

    if loans_collection.find_one({"gold_packet_no": data.gold_packet_no}):
        raise HTTPException(status_code=400, detail="Gold packet number already exists")

    # =====================================================
    # CALCULATE ELIGIBLE AMOUNT
    # =====================================================
    total_eligible = 0
    total_net_weight = 0
    items_data = []

    for item in data.items:

        rate = gold_rates_loans_collection.find_one({
            "carat": item.purity.lower()
        })

        if not rate:
            raise HTTPException(
                status_code=400,
                detail=f"Gold rate not found for {item.purity}"
            )

        net_weight = item.net_weight
        eligible_value = net_weight * rate["eligible_loan_per_gram"]

        total_eligible += eligible_value
        total_net_weight += net_weight

        items_data.append({
            "gold_type": item.gold_type,
            "item_type": item.item_type,
            "purity": item.purity,
            "gross_weight": item.gross_weight,
            "stone_weight": item.stone_weight,
            "dust_weight": item.dust_weight,
            "wax_weight": item.wax_weight,
            "net_weight": net_weight,
            "eligible_value": eligible_value
        })

    # =====================================================
    # LOAN AMOUNT VALIDATION
    # =====================================================
    if data.loan_amount > total_eligible:
        raise HTTPException(
            status_code=400,
            detail="Loan amount exceeds eligible value"
        )

    # =====================================================
    # STATUS
    # =====================================================
    status = "approved" if user.get("role") == "admin" else "pending"

    # =====================================================
    # CREATED BY
    # =====================================================
    if user.get("role") == "staff":
        user_id = user.get("_id") or user.get("id")

        if not user_id:
            raise HTTPException(status_code=400, detail="User ID missing")

        if not isinstance(user_id, ObjectId):
            user_id = ObjectId(user_id)

        staff = staffs_collection.find_one({"_id": user_id})
        if not staff:
            raise HTTPException(status_code=404, detail="Staff not found")

        created_by = {
            "id": str(staff["_id"]),
            "name": staff.get("firstname", "") + " " + staff.get("lastname", ""),
            "role": "staff"
        }

    else:
        admin_id = user.get("_id") or user.get("id")

        if admin_id and not isinstance(admin_id, ObjectId):
            admin_id = ObjectId(admin_id)

        created_by = {
            "id": str(admin_id) if admin_id else None,
            "name": user.get("name", "Admin"),
            "role": "admin"
        }

    # =====================================================
    # CREATE LOAN DOCUMENT
    # =====================================================
    loan_doc = {
        "loan_no": data.loan_no,
        "gold_packet_no": data.gold_packet_no,
        "image": data.image,
        "customer_id": customer["_id"],
        "customer_code": customer.get("customer_code"),
        "customer_name": customer.get("firstname", "") + " " + customer.get("lastname", ""),
        "scheme_id": scheme["_id"],
        "scheme_name": scheme.get("scheme_name"),
        "loan_amount": data.loan_amount,
        "interest_rate": scheme.get("interest_rate"),
        "interest_amount": data.loan_amount * (scheme.get("interest_rate") / 100),
        "loan_date": datetime.combine(data.loan_date, datetime.min.time()),
        "total_eligible_amount": total_eligible,
        "total_net_weight": total_net_weight,
        "items": items_data,
        "status": status,
        "created_by": created_by,
        "created_at": datetime.utcnow()
    }

    # =====================================================
    # INSERT LOAN
    # =====================================================
    result = loans_collection.insert_one(loan_doc)

    # =====================================================
    # RESPONSE
    # =====================================================
    return {
        "loan_id": str(result.inserted_id),
        "loan_no": data.loan_no,
        "gold_packet_no": data.gold_packet_no,
        "customer_id": str(customer["_id"]),
        "customer_name": loan_doc["customer_name"],
        "loan_amount": data.loan_amount,
        "total_eligible_amount": total_eligible,
        "total_net_weight": total_net_weight,
        "status": status,
        "created_by": created_by
    }

@router.put("/loan/updateapproval/{id}")
def update_loan_approval(id: str, user=Depends(admin_required)):

    loan = loans_collection.find_one({"_id": ObjectId(id)})

    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if loan["status"] != "pending":
        raise HTTPException(status_code=400, detail="Only pending loans can be updated")

    loans_collection.update_one(
        {"_id": ObjectId(id)},
        {
            "$set": {
                "status": "approved",
                "updated_at": datetime.utcnow()
            }
        }
    )

    return {"message": "Loan approved"}

@router.put("/loan/update/{id}")
def update_loan(id: str, data: LoanUpdate, user=Depends(admin_required)):

    loan = loans_collection.find_one({"_id": ObjectId(id)})

    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if loan["status"] != "pending":
        raise HTTPException(status_code=400, detail="Only pending loans can be updated")

    update_doc = {}

    if data.scheme_id:
        scheme = scheme_collection.find_one({"_id": ObjectId(data.scheme_id)})

        if not scheme:
            raise HTTPException(status_code=404, detail="Scheme not found")

        update_doc["scheme_id"] = scheme["_id"]
        update_doc["scheme_name"] = scheme["scheme_name"]

    if data.loan_amount:
        update_doc["loan_amount"] = data.loan_amount

    if data.loan_date:
        update_doc["loan_date"] = data.loan_date

    if data.image:
        update_doc["image"] = data.image

    update_doc["updated_at"] = datetime.utcnow()

    loans_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": update_doc}
    )

    return {"message": "Loan updated successfully"}