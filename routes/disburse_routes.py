from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from datetime import datetime, timedelta
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


# =====================================================
# DATE UTILITIES
# =====================================================

def is_leap_year(date):
    """Check if year is leap year"""
    y = date.year
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def get_days_in_year(date):
    """Get days in year (365 or 366)"""
    return 366 if is_leap_year(date) else 365


def calculate_actual_days(start_date, end_date):
    """
    Calculate actual number of days between two dates
    INCLUDING the end date for interest calculation
    """
    if not start_date or not end_date:
        return 0
    
    delta = (end_date - start_date).days + 1
    return delta


def calculate_interest_for_period(principal, rate, start_date, end_date):
    """
    Calculate total interest for a period using actual days
    INCLUDES both start and end dates
    """
    if not start_date or not end_date:
        return 0
    
    days = calculate_actual_days(start_date, end_date)
    if days <= 0:
        return 0
    
    days_in_year = get_days_in_year(end_date)
    interest = (principal * rate * days) / (100 * days_in_year)
    return round(interest, 2)


def calculate_daily_interest(principal, rate, date):
    """
    Calculate daily interest based on actual days in year
    """
    days_in_year = get_days_in_year(date)
    daily_interest = (principal * rate) / (100 * days_in_year)
    return round(daily_interest, 4)


def validate_date(date):
    """Adjust invalid dates"""
    if not date:
        return date
    
    try:
        day = date.day
        month = date.month
        year = date.year
        
        if month == 2 and day > 28:
            if is_leap_year(date):
                return date.replace(day=29)
            else:
                return date.replace(day=28)
        
        if month == 4 and day == 31:
            return date.replace(day=30)
        
        if month in [6, 9, 11] and day == 31:
            return date.replace(day=30)
        
        return date
    except:
        return date


def calculate_next_due_date(start_date, tenure_months):
    """
    Calculate next due date with proper month-end handling
    """
    due_date = start_date + relativedelta(months=tenure_months)
    return validate_date(due_date)


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
            "disbursement_id": disbursement.inserted_id,
            "outstanding_principal": loan["loan_amount"]
        }}
    )

    # =========================
    # GET SCHEME - IMPORTANT: Read grace_speed correctly
    # =========================
    scheme = scheme_collection.find_one({"_id": loan["scheme_id"]})
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")

    repayment_type = scheme.get("Repayment_type", "").lower()
    
    # IMPORTANT: Get grace_speed from scheme (not grace_days)
    # The field in scheme is "grace_speed"
    grace_days = scheme.get("grace_speed", 0)  # ← THIS IS THE KEY FIX
    
    print(f"Scheme: {scheme.get('scheme_name')}, Grace Days: {grace_days}")  # Debug log

    # =====================================================
    # EMI SCHEME → MULTIPLE DUES
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
            # Get the due date for this EMI
            due_date = row["due_date"]
            
            # Calculate cycle end date INCLUDING grace period
            if grace_days > 0:
                cycle_end_date = due_date + timedelta(days=grace_days)
                cycle_end_date = validate_date(cycle_end_date)
            else:
                cycle_end_date = due_date
            
            # Calculate days in cycle INCLUDING grace period
            interest_start_date = now if row["installment_no"] == 1 else row["due_date"]
            days_in_cycle_with_grace = calculate_actual_days(interest_start_date, cycle_end_date)
            
            # Calculate daily interest
            daily_interest = calculate_daily_interest(principal, rate, due_date)
            
            # Calculate total interest INCLUDING grace period
            total_interest_with_grace = daily_interest * days_in_cycle_with_grace
            
            due_list.append({
                "loan_id": loan["_id"],
                "loan_no": loan["loan_no"],
                "customer_id": loan["customer_id"],
                "customer_name": loan["customer_name"],

                "installment_no": row["installment_no"],
                "due_date": due_date,
                "grace_period_end_date": cycle_end_date,  # Store grace end date
                
                "emi_amount": row["emi_amount"],
                "interest_due": round(total_interest_with_grace, 2),
                "principal_due": row["principal_due"],
                
                # Daily interest
                "daily_interest": daily_interest,
                "interest_rate": rate,
                
                # Grace period (from scheme's grace_speed)
                "grace_days": grace_days,
                "days_in_cycle_with_grace": days_in_cycle_with_grace,
                
                # Penalty tracking
                "penalty_rate": scheme.get("penalty_percent", 0),

                "pending_amount": round(total_interest_with_grace + row["principal_due"], 2),

                "interest_paid": 0,
                "principal_paid": 0,
                "penalty_paid": 0,
                "paid_amount": 0,

                "status": "pending",
                "created_at": now
            })

        loan_dues_collection.insert_many(due_list)
        
        return {
            "message": "Loan disbursed successfully",
            "repayment_type": "EMI",
            "details": {
                "loan_amount": loan["loan_amount"],
                "interest_rate": scheme["interest_rate"],
                "total_emis": len(schedule),
                "emi_amount": schedule[0]["emi_amount"] if schedule else None,
                "grace_days": grace_days,
                "note": f"Interest calculated including {grace_days} grace days. Overdue includes grace days."
            }
        }

   
    # =====================================================
    # BULLET SCHEME → CREATE INTEREST CYCLES
    # =====================================================
    elif repayment_type == "bullet":

        existing_due = loan_dues_collection.find_one({"loan_id": loan["_id"]})
        if existing_due:
            return {"message": "Bullet due already created"}

        start_date = now
        principal = loan["loan_amount"]
        rate = scheme["interest_rate"]
        tenure_months = scheme.get("tenure_months", 1)  # From scheme: 1 month
        total_tenure_months = scheme.get("total_tenure_months", 24)  # From scheme: 24 months
        
        # IMPORTANT: Get grace_speed from scheme
        grace_days = scheme.get("grace_speed", 0)  # From scheme: 10 days
        
        print(f"Bullet Loan - Grace Days: {grace_days}")  # Debug log
        
        # Calculate maturity date
        maturity_date = calculate_next_due_date(start_date, total_tenure_months)
        
        # Calculate regular due date (without grace)
        regular_due_date = calculate_next_due_date(start_date, tenure_months)
        
        # Calculate cycle end date INCLUDING grace period
        # Interest accrues until this date
        if grace_days > 0:
            cycle_end_date = regular_due_date + timedelta(days=grace_days)
            cycle_end_date = validate_date(cycle_end_date)
        else:
            cycle_end_date = regular_due_date
        
        # Calculate days in cycle INCLUDING grace period
        days_in_cycle_with_grace = calculate_actual_days(start_date, cycle_end_date)
        
        # Calculate regular days (without grace) for reference
        regular_days = calculate_actual_days(start_date, regular_due_date)
        
        # Calculate daily interest
        daily_interest = calculate_daily_interest(principal, rate, start_date)
        
        # Calculate total interest for the cycle INCLUDING grace period
        total_cycle_interest = calculate_interest_for_period(principal, rate, start_date, cycle_end_date)
        
        # Create first due record
        loan_dues_collection.insert_one({
            "loan_id": loan["_id"],
            "loan_no": loan["loan_no"],
            "customer_id": loan["customer_id"],
            "customer_name": loan["customer_name"],
            "customer_code": loan.get("customer_code"),

            # CORE VALUES
            "principal": principal,
            "interest_rate": rate,
            "annual_interest_amount": round((principal * rate) / 100, 2),
            
            # CYCLE INFORMATION
            "cycle_number": 1,
            "total_cycles": (total_tenure_months // tenure_months) if tenure_months > 0 else 1,
            "is_final_cycle": False,
            
            # DAYS AND INTEREST (WITH GRACE)
            "interest_per_day": daily_interest,
            "regular_due_date": regular_due_date,
            "cycle_end_date_with_grace": cycle_end_date,  # Interest calculation end date
            "days_in_cycle_with_grace": days_in_cycle_with_grace,
            "regular_days": regular_days,  # For reference
            "total_cycle_interest": total_cycle_interest,
            "grace_days": grace_days,  # Store grace days from scheme

            # DATES
            "loan_start_date": start_date,
            "interest_start_date": start_date,
            "due_date": regular_due_date,
            "maturity_date": maturity_date,

            # TRACKING
            "interest_due": total_cycle_interest,
            "interest_paid": 0,
            "principal_paid": 0,
            "penalty_paid": 0,
            "penalty_due": 0,
            
            # PENALTY TRACKING
            "penalty_rate": scheme.get("penalty_percent", 0),
            "last_penalty_update": None,
            "overdue_days": 0,

            "pending_amount": total_cycle_interest,
            "status": "pending",
            "created_at": now
        })
        
        # Store loan-level information
        loans_collection.update_one(
            {"_id": loan["_id"]},
            {"$set": {
                "repayment_type": "bullet",
                "interest_cycle_months": tenure_months,
                "total_tenure_months": total_tenure_months,
                "next_cycle_start_date": cycle_end_date,
                "current_cycle_number": 1,
                "total_cycles": (total_tenure_months // tenure_months) if tenure_months > 0 else 1,
                "grace_days": grace_days
            }}
        )

        return {
            "message": "Loan disbursed successfully",
            "repayment_type": "BULLET",
            "details": {
                "loan_amount": loan["loan_amount"],
                "interest_rate": rate,
                "interest_cycle_months": tenure_months,
                "total_tenure_months": total_tenure_months,
                "daily_interest": daily_interest,
                "regular_due_date": regular_due_date,
                "cycle_end_date_with_grace": cycle_end_date,
                "regular_days": regular_days,
                "grace_days_added": grace_days,
                "total_days_in_cycle": days_in_cycle_with_grace,
                "first_cycle_interest": total_cycle_interest,
                "maturity_date": maturity_date,
                "total_cycles": (total_tenure_months // tenure_months) if tenure_months > 0 else 1,
                "grace_days": grace_days,
                "note": f"Interest calculated including {grace_days} grace days. Overdue includes grace days."
            }
        }

    else:
        raise HTTPException(status_code=400, detail="Invalid repayment type")