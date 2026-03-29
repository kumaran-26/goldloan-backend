from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId # Add InvalidId import
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel
from bson.errors import InvalidId


from database.db import (
    loans_collection,
    scheme_collection,
    customers_collection,
    gold_rate_collection,
    staffs_collection
)

from utils.auth import admin_or_staff_required, admin_required
from schemas.loan import LoanCreate, LoanUpdate

router = APIRouter(prefix="/loans-api", tags=["loans"])






# =====================================================
# CREATE LOAN
# =====================================================
@router.post("/create/{id}")
def create_loan(id: str, data: LoanCreate, user=Depends(admin_or_staff_required)):

    # ---------- CUSTOMER ----------
    try:
        customer_id = ObjectId(id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid customer ID format")

    customer = customers_collection.find_one({"_id": customer_id})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # ---------- SCHEME ----------
    try:
        scheme_id = ObjectId(data.scheme_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid scheme_id format")

    scheme = scheme_collection.find_one({"_id": scheme_id, "status": "active"})
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")

    # ---------- DUPLICATE CHECK ----------
    if loans_collection.find_one({"loan_no": data.loan_no}):
        raise HTTPException(status_code=400, detail="Loan number already exists")

    if loans_collection.find_one({"gold_packet_no": data.gold_packet_no}):
        raise HTTPException(status_code=400, detail="Gold packet number already exists")

    # =====================================================
    # CALCULATION
    # =====================================================
    total_eligible = 0
    total_net_weight = 0
    total_amount = 0
    items_data = []

    for item in data.items:
        purity = item.purity.lower()

        carat_purity = gold_rate_collection.find_one({"carat": purity})
        if not carat_purity:
            raise HTTPException(
                status_code=400,
                detail=f"Gold rate not found for purity: {item.purity}"
            )

        # ---------- NET WEIGHT ----------
        net_weight = (
            item.gross_weight
            - item.stone_weight
            - item.dust_weight
            - item.wax_weight
        )

        if net_weight <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid net weight for item {item.item_type}"
            )

        # ---------- GOLD RATE & LTV ----------
        gold_rate = carat_purity.get("gold_rate", 0)
        ltv = carat_purity.get("ltv", 0)

        if gold_rate <= 0 or ltv <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid gold rate/LTV for purity: {item.purity}"
            )

        # ---------- TOTAL VALUE ----------
        total_value = net_weight * gold_rate

        # ---------- ELIGIBLE VALUE ----------
        eligible_per_gram = (gold_rate * ltv) / 100
        eligible_value = net_weight * eligible_per_gram

        total_amount += total_value
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
            "net_weight": round(net_weight, 3),
            "market_value": round(total_value, 2),
            "eligible_value": round(eligible_value, 2),
            "rate_used": gold_rate,
            "ltv_used": ltv
        })

    # =====================================================
    # 🔥 VALIDATIONS (IMPORTANT)
    # =====================================================

    # Broker Rule (Market Value)
    if data.loan_amount > total_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Loan exceeds total gold value ({round(total_amount, 2)})"
        )

    # Bank Rule (LTV)
    if data.loan_amount > total_eligible:
        raise HTTPException(
            status_code=400,
            detail=f"Loan exceeds eligible amount ({round(total_eligible, 2)})"
        )

    # =====================================================
    # DATE
    # =====================================================
    if isinstance(data.loan_date, date):
        loan_date = datetime.combine(data.loan_date, datetime.min.time())
    elif isinstance(data.loan_date, str):
        loan_date = datetime.strptime(data.loan_date, "%Y-%m-%d")
    else:
        loan_date = datetime.utcnow()

    # =====================================================
    # STATUS
    # =====================================================
    status = "approved" if user.get("role") == "admin" else "pending"

    # =====================================================
    # CREATED BY
    # =====================================================
    user_id = user.get("_id") or user.get("id")

    if user.get("role") == "staff":
        user_id = ObjectId(user_id)
        staff = staffs_collection.find_one({"_id": user_id})

        created_by = {
            "id": str(user_id),
            "name": staff.get("firstname", "") + " " + staff.get("lastname", ""),
            "role": "staff"
        }
    else:
        created_by = {
            "id": str(user_id),
            "name": user.get("name", "Admin"),
            "role": "admin"
        }

    # =====================================================
    # INTEREST
    # =====================================================
    interest_rate = scheme.get("interest_rate", 0)
    interest_amount = (data.loan_amount * interest_rate) / 100

    # =====================================================
    # SAVE
    # =====================================================
    loan_doc = {
        "loan_no": data.loan_no,
        "gold_packet_no": data.gold_packet_no,
        "image": data.image,
        "customer_id": customer["_id"],
        "customer_name": customer.get("firstname", "") + " " + customer.get("lastname", ""),
        "scheme_id": scheme["_id"],
        "scheme_name": scheme.get("scheme_name"),
        "loan_amount": data.loan_amount,
        "interest_rate": interest_rate,
        "interest_amount": round(interest_amount, 2),
        "loan_date": loan_date,
        "total_market_value": round(total_amount, 2),
        "total_eligible_amount": round(total_eligible, 2),
        "total_net_weight": round(total_net_weight, 3),
        "items": items_data,
        "status": status,
        "created_by": created_by,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    result = loans_collection.insert_one(loan_doc)

    return {
        "loan_id": str(result.inserted_id),
        "loan_no": data.loan_no,
        "loan_amount": data.loan_amount,
        "total_market_value": round(total_amount, 2),
        "total_eligible_amount": round(total_eligible, 2),
        "status": status,
        "message": "Loan created successfully"
    }


@router.put("/loan/updateapproval/{id}")
def update_loan_approval(id: str, user=Depends(admin_required)):
    
    try:
        loan_id = ObjectId(id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid loan ID format")

    loan = loans_collection.find_one({"_id": loan_id})

    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if loan["status"] != "pending":
        raise HTTPException(status_code=400, detail="Only pending loans can be approved")

    loans_collection.update_one(
        {"_id": loan_id},
        {
            "$set": {
                "status": "approved",
                "approved_by": user.get("name", "Admin"),
                "approved_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
        }
    )

    return {
        "message": "Loan approved successfully",
        "loan_id": id,
        "loan_no": loan.get("loan_no"),
        "status": "approved"
    }

@router.put("/loan/update/{id}")
def update_loan(id: str, data: LoanUpdate, user=Depends(admin_required)):

    # VALIDATE LOAN ID
  
    try:
        loan_id = ObjectId(id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid loan ID format")

    # GET LOAN
  
    loan = loans_collection.find_one({"_id": loan_id})
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

   
    # STATUS CHECK
  
    if loan.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Only pending loans can be updated")

    update_doc = {}

    # SCHEME UPDATE
    
    if data.scheme_id:
        try:
            scheme_id = ObjectId(data.scheme_id)
        except InvalidId:
            raise HTTPException(status_code=400, detail="Invalid scheme_id format")

        scheme = scheme_collection.find_one({"_id": scheme_id, "status": "active"})
        if not scheme:
            raise HTTPException(status_code=404, detail="Scheme not found")

        update_doc["scheme_id"] = scheme["_id"]
        update_doc["scheme_name"] = scheme.get("scheme_name")
        update_doc["interest_rate"] = scheme.get("interest_rate", 0)

    # LOAN AMOUNT UPDATE + VALIDATION 
   
    if data.loan_amount:

        total_eligible = loan.get("total_eligible_amount", 0)
        total_market = loan.get("total_market_value", 0)

        # Broker Rule
        if data.loan_amount > total_market:
            raise HTTPException(
                status_code=400,
                detail=f"Loan exceeds total gold value ({round(total_market, 2)})"
            )

        # Bank Rule
        if data.loan_amount > total_eligible:
            raise HTTPException(
                status_code=400,
                detail=f"Loan exceeds eligible amount ({round(total_eligible, 2)})"
            )

        update_doc["loan_amount"] = data.loan_amount


    # INTEREST RECALCULATION
  
    if data.loan_amount or data.scheme_id:

        loan_amount = update_doc.get("loan_amount", loan.get("loan_amount"))
        interest_rate = update_doc.get("interest_rate", loan.get("interest_rate", 0))

        update_doc["interest_amount"] = (loan_amount * interest_rate) / 100

    # =====================================================
    # DATE UPDATE
    # =====================================================
    if data.loan_date:
        if isinstance(data.loan_date, date):
            update_doc["loan_date"] = datetime.combine(data.loan_date, datetime.min.time())
        elif isinstance(data.loan_date, str):
            update_doc["loan_date"] = datetime.strptime(data.loan_date, "%Y-%m-%d")
        else:
            update_doc["loan_date"] = data.loan_date

 
    if data.image:
        update_doc["image"] = data.image

   
    # EMPTY CHECK
  
    if not update_doc:
        raise HTTPException(status_code=400, detail="No fields to update")

    update_doc["updated_at"] = datetime.utcnow()

    
    # UPDATE DB
    
    result = loans_collection.update_one(
        {"_id": loan_id},
        {"$set": update_doc}
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=400, detail="No changes made to the loan")

   
    return {
        "message": "Loan updated successfully",
        "loan_id": id,
        "updated_fields": list(update_doc.keys())
    }