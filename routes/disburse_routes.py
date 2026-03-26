from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from datetime import datetime
from dateutil.relativedelta import relativedelta

from utils.auth import admin_or_staff_required
from database.db import (
    loans_collection,
    disbursements_collection,
    scheme_collection,
    transactions_collection,
    loan_dues_collection
)

from services.emi_service import generate_emi_schedule

router = APIRouter(prefix="/disburse", tags=["Disbursement"])


@router.post("/loan/disburse/{loan_id}")
def disburse_loan(loan_id: str, user=Depends(admin_or_staff_required)):

    # =========================
    # VALIDATE LOAN
    # =========================
    try:
        loan_obj_id = ObjectId(loan_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid loan_id")

    loan = loans_collection.find_one({"_id": loan_obj_id})
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if loan.get("status") != "approved":
        raise HTTPException(status_code=400, detail="Loan not approved")

    # =========================
    # ALREADY DISBURSED CHECK
    # =========================
    if disbursements_collection.find_one({"loan_id": loan_obj_id}):
        raise HTTPException(status_code=400, detail="Loan already disbursed")

    now = datetime.utcnow()

    # =========================
    # DISBURSE ENTRY
    # =========================
    disbursement = disbursements_collection.insert_one({
        "loan_id": loan["_id"],
        "loan_no": loan.get("loan_no"),
        "customer_id": loan.get("customer_id"),
        "customer_name": loan.get("customer_name"),
        "disburse_amount": loan.get("loan_amount"),
        "disburse_date": now,
        "status": "completed",
        "created_at": now
    })

    # =========================
    # TRANSACTION ENTRY
    # =========================
    transactions_collection.insert_one({
        "loan_id": loan["_id"],
        "loan_no": loan.get("loan_no"),
        "transaction_type": "debit",
        "payment_type": "disbursement",
        "amount": loan.get("loan_amount"),
        "payment_mode": "cash",
        "transaction_date": now,
        "created_at": now
    })

    # =========================
    # UPDATE LOAN
    # =========================
    loans_collection.update_one(
        {"_id": loan["_id"]},
        {"$set": {
            "status": "active",
            "loan_start_date": now,
            "disbursement_id": disbursement.inserted_id
        }}
    )

    # =========================
    # GET SCHEME
    # =========================
    scheme = scheme_collection.find_one({"_id": loan["scheme_id"]})
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")

    repayment_type = scheme.get("Repayment_type", "").lower()

    # =====================================================
    # ✅ EMI SCHEME → MULTIPLE DUES
    # =====================================================
    if repayment_type == "emi":

        existing_due = loan_dues_collection.find_one({"loan_id": loan["_id"]})
        if existing_due:
            return {"message": "EMI dues already created"}

        principal = loan["loan_amount"]
        rate = scheme["interest_rate"]
        tenure = scheme["total_tenure_months"]

        schedule = generate_emi_schedule(principal, rate, tenure, now)

        due_list = []

        for row in schedule:
            due_list.append({
                "loan_id": loan["_id"],
                "loan_no": loan["loan_no"],
                "customer_id": loan["customer_id"],
                "customer_name": loan["customer_name"],

                "installment_no": row["installment_no"],
                "due_date": row["due_date"],

                "emi_amount": row["emi_amount"],
                "interest_due": row["interest_due"],
                "principal_due": row["principal_due"],

                "pending_amount": row["emi_amount"],

                "interest_paid": 0,
                "principal_paid": 0,
                "penalty_paid": 0,
                "paid_amount": 0,

                "status": "pending",
                "created_at": now
            })

        loan_dues_collection.insert_many(due_list)

    # =====================================================
    # ✅ BULLET SCHEME → ONLY ONE ACTIVE DUE
    # =====================================================
    elif repayment_type == "bullet":

        existing_due = loan_dues_collection.find_one({"loan_id": loan["_id"]})
        if existing_due:
            return {"message": "Bullet due already created"}

        start_date = now

        maturity_date = start_date + relativedelta(
            months=scheme.get("total_tenure_months", 12)
        )

        overdue_date = start_date + relativedelta(
            months=scheme.get("tenure_months", 3)
        )

        loan_dues_collection.insert_one({
            "loan_id": loan["_id"],
            "loan_no": loan["loan_no"],
            "customer_id": loan["customer_id"],
            "customer_name": loan["customer_name"],
            "customer_code": loan.get("customer_code"),

            # 🔥 CORE VALUES
            "principal": loan["loan_amount"],
            "interest_rate": scheme["interest_rate"],
            "interest_amount": loan.get("interest_amount", 0),

            # 🔥 DATES
            "loan_start_date": start_date,
            "interest_start_date": start_date,
            "overdue_date": overdue_date,
            "maturity_date": maturity_date,

            # 🔥 TRACKING
            "interest_due": 0,
            "interest_paid": 0,
            "principal_paid": 0,
            "penalty_paid": 0,

            "pending_amount": loan["loan_amount"],

            # 🔥 IMPORTANT
            "status": "active",
            "created_at": now
        })

    else:
        raise HTTPException(status_code=400, detail="Invalid repayment type")

    return {
        "message": "Loan disbursed successfully",
        "repayment_type": repayment_type.upper()
    }