from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime, timedelta
from bson import ObjectId
from utils.auth import admin_required
from dateutil.relativedelta import relativedelta
from database.db import (
    loans_collection,
    transactions_collection,
    loan_dues_collection,
    scheme_collection
)

router = APIRouter(prefix="/loan", tags=["Loan Payments"])


# =====================================================
# LEAP YEAR
# =====================================================
def is_leap_year(date):
    y = date.year
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def close_loan_if_done(loan_id):
    pending = loan_dues_collection.count_documents({
        "loan_id": ObjectId(loan_id),
        "status": {"$in": ["active", "partial"]}
    })

    loan = loans_collection.find_one({"_id": ObjectId(loan_id)})

    if not loan:
        return

    if pending == 0 and round(loan.get("loan_amount", 0), 2) <= 0:
        loans_collection.update_one(
            {"_id": ObjectId(loan_id)},
            {"$set": {
                "status": "closed",
                "closed_date": datetime.utcnow()
            }}
        )


# =====================================================
# TRANSACTIONS
# =====================================================
def create_transactions(loan, loan_id, payment_mode,
                        interest_paid, principal_paid, penalty_paid, extra):

    now = datetime.utcnow()

    def insert(ptype, amt):
        if amt <= 0:
            return
        transactions_collection.insert_one({
            "loan_id": ObjectId(loan_id),
            "loan_no": loan.get("loan_no"),
            "transaction_type": "credit",
            "payment_type": ptype,
            "amount": round(amt, 2),
            "payment_mode": payment_mode,
            "transaction_date": now,
            "created_at": now
        })

    insert("interest paid", interest_paid)
    insert("principal paid", principal_paid)
    insert("penalty paid", penalty_paid)
    insert("extra payment", extra)


# =====================================================
# PENALTY CALCULATION - BANK STANDARD
# =====================================================
def calculate_overdue_penalty(overdue_amount, interest_rate, penalty_rate, due_date, payment_date=None):
    """
    Calculate penalty using Effective Rate (Interest Rate + Penalty Rate)
    
    Formula: 
    Overdue Penalty = Overdue Amount × (Interest Rate + Penalty Rate) × Days Overdue / 365
    
    Example 1 (Bullet Loan):
    Overdue Amount = ₹7,000
    Interest Rate = 12%
    Penalty Rate = 3%
    Effective Rate = 15%
    Days Overdue = 10
    Penalty = 7000 × 15% × 10 / 365 = ₹28.77
    
    Example 2 (Interest Only):
    Overdue Amount = ₹982.5
    Interest Rate = 15%
    Penalty Rate = 3%
    Effective Rate = 18%
    Days Overdue = 10
    Penalty = 982.5 × 18% × 10 / 365 = ₹4.84
    """
    if payment_date is None:
        payment_date = datetime.utcnow()
    
    if payment_date <= due_date:
        return 0, 0
    
    days_overdue = (payment_date - due_date).days
    effective_rate = interest_rate + penalty_rate  # Interest + Penalty
    
    # Calculate penalty on overdue amount
    penalty = (overdue_amount * effective_rate * days_overdue) / (100 * 365)
    
    return round(penalty, 2), days_overdue


def calculate_emi_overdue_penalty(emi_amount, interest_rate, penalty_rate, due_date, payment_date=None):
    """
    Calculate penalty for EMI overdue
    
    Formula:
    Overdue Charge = EMI × (Interest Rate + Penalty Rate) × Days Overdue / 365
    
    Example:
    EMI = ₹3,800
    Interest Rate = 15%
    Penalty Rate = 3%
    Effective Rate = 18%
    Days Overdue = 10
    Penalty = 3800 × 18% × 10 / 365 = ₹18.74
    """
    if payment_date is None:
        payment_date = datetime.utcnow()
    
    if payment_date <= due_date:
        return 0, 0
    
    days_overdue = (payment_date - due_date).days
    effective_rate = interest_rate + penalty_rate
    
    penalty = (emi_amount * effective_rate * days_overdue) / (100 * 365)
    
    return round(penalty, 2), days_overdue


# =====================================================
# MAIN API - ADMIN ONLY
# =====================================================
@router.post("/pay/{loan_id}", dependencies=[Depends(admin_required)])
def pay_loan(
    loan_id: str, 
    amount: float, 
    payment_mode: str = "cash"
):
    """
    Process loan payment
    🔐 ADMIN ONLY ACCESS
    """
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid amount")

    try:
        loan = loans_collection.find_one({"_id": ObjectId(loan_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid loan ID")

    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if loan.get("status") == "closed":
        raise HTTPException(status_code=400, detail="Loan already closed")

    scheme = scheme_collection.find_one({"_id": loan["scheme_id"]})
    if not scheme:
        raise HTTPException(status_code=404, detail="Scheme not found")

    if scheme.get("Repayment_type", "").lower() == "emi":
        return handle_emi_payment(loan, scheme, loan_id, amount, payment_mode)
    else:
        return handle_bullet_payment(loan, scheme, loan_id, amount, payment_mode)
    

# =====================================================
# EMI PAYMENT HANDLER WITH CORRECT PENALTY
# =====================================================
def handle_emi_payment(loan, scheme, loan_id, amount, payment_mode):
    """
    Handle EMI loan payments with correct penalty calculation
    Penalty uses Effective Rate = Interest Rate + Penalty Rate
    """
    today = datetime.utcnow()
    remaining = amount
    
    total_interest_paid = 0
    total_principal_paid = 0
    total_penalty_paid = 0
    
    # Get all pending EMIs in order
    pending_emis = list(loan_dues_collection.find(
        {
            "loan_id": ObjectId(loan_id),
            "status": {"$in": ["pending", "partial"]}
        },
        sort=[("installment_no", 1)]
    ))
    
    if not pending_emis:
        raise HTTPException(status_code=400, detail="No pending dues found")
    
    # Get interest rate and penalty rate from scheme
    interest_rate = scheme.get("interest_rate", 0)
    penalty_rate = scheme.get("penalty_percent", 0)
    
    # Process current EMI and any pending from previous months
    for idx, current_due in enumerate(pending_emis):
        if remaining <= 0:
            break
        
        # Get current EMI details
        interest_due = current_due.get("interest_due", 0) - current_due.get("interest_paid", 0)
        principal_due = current_due.get("principal_due", 0) - current_due.get("principal_paid", 0)
        emi_total = interest_due + principal_due
        
        # ✅ Calculate penalty using Effective Rate method
        due_date = current_due.get("due_date")
        penalty_amount, overdue_days = calculate_emi_overdue_penalty(
            emi_total,
            interest_rate,
            penalty_rate,
            due_date,
            today
        )
        
        # Get existing penalty paid
        penalty_paid_already = current_due.get("penalty_paid", 0)
        penalty_due = max(0, penalty_amount - penalty_paid_already)
        
        # Payment allocation: Penalty → Interest → Principal
        penalty_paid = min(remaining, penalty_due)
        remaining -= penalty_paid
        
        interest_paid = min(remaining, interest_due)
        remaining -= interest_paid
        
        principal_paid = min(remaining, principal_due)
        remaining -= principal_paid
        
        # Calculate balances
        interest_balance = interest_due - interest_paid
        principal_balance = principal_due - principal_paid
        penalty_balance = penalty_due - penalty_paid
        
        pending = interest_balance + principal_balance + penalty_balance
        
        # Determine status
        if pending == 0:
            status = "paid"
        else:
            status = "partial"
        
        # Update current EMI
        new_interest_paid = current_due.get("interest_paid", 0) + interest_paid
        new_principal_paid = current_due.get("principal_paid", 0) + principal_paid
        new_penalty_paid = current_due.get("penalty_paid", 0) + penalty_paid
        new_paid_amount = current_due.get("paid_amount", 0) + (penalty_paid + interest_paid + principal_paid)
        
        update_data = {
            "interest_paid": round(new_interest_paid, 2),
            "principal_paid": round(new_principal_paid, 2),
            "penalty_paid": round(new_penalty_paid, 2),
            "penalty_due": penalty_amount,  # Store calculated penalty
            "paid_amount": round(new_paid_amount, 2),
            "pending_amount": round(pending, 2),
            "status": status,
            "last_paid_date": today,
            "overdue_days": overdue_days,
            "effective_rate_applied": interest_rate + penalty_rate
        }
        
        if status == "paid":
            update_data["paid_date"] = today
        
        loan_dues_collection.update_one(
            {"_id": current_due["_id"]},
            {"$set": update_data}
        )
        
        total_interest_paid += interest_paid
        total_principal_paid += principal_paid
        total_penalty_paid += penalty_paid
        
        # If current EMI is fully paid and there's excess, handle next EMI
        if status == "paid" and remaining > 0 and idx < len(pending_emis) - 1:
            # Get next EMI
            next_due = pending_emis[idx + 1]
            
            # Get next EMI details
            next_interest_due = next_due.get("interest_due", 0) - next_due.get("interest_paid", 0)
            next_principal_due = next_due.get("principal_due", 0) - next_due.get("principal_paid", 0)
            next_emi_total = next_interest_due + next_principal_due
            
            if remaining >= next_emi_total:
                # Pay full next EMI
                remaining -= next_emi_total
                
                # Mark next EMI as paid
                loan_dues_collection.update_one(
                    {"_id": next_due["_id"]},
                    {"$set": {
                        "interest_paid": round(next_interest_due, 2),
                        "principal_paid": round(next_principal_due, 2),
                        "paid_amount": round(next_emi_total, 2),
                        "pending_amount": 0,
                        "status": "paid",
                        "paid_date": today,
                        "last_paid_date": today
                    }}
                )
                
                total_interest_paid += next_interest_due
                total_principal_paid += next_principal_due
            else:
                # Partial payment on next EMI
                if remaining <= next_interest_due:
                    # Only pay part of interest
                    interest_to_pay = remaining
                    principal_to_pay = 0
                    remaining = 0
                else:
                    # Pay full interest and part of principal
                    interest_to_pay = next_interest_due
                    remaining -= next_interest_due
                    principal_to_pay = min(remaining, next_principal_due)
                    remaining -= principal_to_pay
                
                # Update next EMI
                new_next_interest_paid = next_due.get("interest_paid", 0) + interest_to_pay
                new_next_principal_paid = next_due.get("principal_paid", 0) + principal_to_pay
                new_next_paid = next_due.get("paid_amount", 0) + (interest_to_pay + principal_to_pay)
                
                next_pending = (next_interest_due - interest_to_pay) + (next_principal_due - principal_to_pay)
                next_status = "partial" if next_pending > 0 else "paid"
                
                loan_dues_collection.update_one(
                    {"_id": next_due["_id"]},
                    {"$set": {
                        "interest_paid": round(new_next_interest_paid, 2),
                        "principal_paid": round(new_next_principal_paid, 2),
                        "paid_amount": round(new_next_paid, 2),
                        "pending_amount": round(next_pending, 2),
                        "status": next_status,
                        "last_paid_date": today
                    }}
                )
                
                if next_status == "paid":
                    loan_dues_collection.update_one(
                        {"_id": next_due["_id"]},
                        {"$set": {"paid_date": today}}
                    )
                
                total_interest_paid += interest_to_pay
                total_principal_paid += principal_to_pay
                
                break  # No more money to pay
    
    # Handle excess payment after all EMIs are paid
    if remaining > 0:
        # Reduce overall loan principal
        current_principal = loan.get("loan_amount", 0)
        new_principal = max(0, current_principal - remaining)
        
        loans_collection.update_one(
            {"_id": ObjectId(loan_id)},
            {"$set": {"loan_amount": round(new_principal, 2)}}
        )
        
        total_principal_paid += remaining
        remaining = 0
    
    # Create transaction records
    create_transactions(
        loan,
        loan_id,
        payment_mode,
        total_interest_paid,
        total_principal_paid,
        total_penalty_paid,
        0
    )
    
    # Check and close loan if all installments are completed
    pending_dues_count = loan_dues_collection.count_documents({
        "loan_id": ObjectId(loan_id),
        "status": {"$in": ["pending", "partial"]}
    })
    
    if pending_dues_count == 0:
        loans_collection.update_one(
            {"_id": ObjectId(loan_id)},
            {"$set": {
                "status": "closed",
                "closed_date": datetime.utcnow()
            }}
        )
    
    updated_loan = loans_collection.find_one({"_id": ObjectId(loan_id)})
    
    return {
        "type": "EMI",
        "interest_paid": round(total_interest_paid, 2),
        "principal_paid": round(total_principal_paid, 2),
        "penalty_paid": round(total_penalty_paid, 2),
        "total_paid": round(total_interest_paid + total_principal_paid + total_penalty_paid, 2),
        "pending_emis": pending_dues_count,
        "loan_status": updated_loan.get("status", "active") if updated_loan else "unknown",
        "message": "Loan closed successfully!" if pending_dues_count == 0 else "Payment processed successfully."
    }


# =====================================================
# BULLET PAYMENT HANDLER WITH CORRECT PENALTY
# =====================================================
def handle_bullet_payment(loan, scheme, loan_id, amount, payment_mode):
    """
    Bullet loan payment handler with correct penalty calculation
    Penalty uses Effective Rate = Interest Rate + Penalty Rate on overdue principal
    """
    today = datetime.utcnow()
    remaining = amount
    
    total_interest_paid = 0
    total_principal_paid = 0
    total_penalty_paid = 0
    
    # GET CURRENT ACTIVE DUE
    due = loan_dues_collection.find_one(
        {"loan_id": ObjectId(loan_id), "status": "active"},
        sort=[("created_at", -1)]
    )
    
    if not due:
        raise HTTPException(status_code=400, detail="No active due found")
    
    # Get current loan details
    principal = due.get("principal", 0)
    rate = due.get("interest_rate", 0)  # Base interest rate
    penalty_rate = scheme.get("penalty_percent", 0)
    tenure_months = scheme.get("tenure_months", 3)
    
    # Get due dates
    interest_start = due.get("interest_start_date")
    overdue_date = due.get("overdue_date")
    maturity_date = due.get("maturity_date")
    
    # =====================================================
    # CALCULATE ACCRUED INTEREST (Regular Interest)
    # =====================================================
    days_diff = (today - interest_start).days
    days = max(days_diff, 1)
    
    days_in_year = 366 if is_leap_year(today) else 365
    daily_interest = (principal * rate) / (100 * days_in_year)
    total_interest = daily_interest * days
    
    # =====================================================
    # CALCULATE OVERDUE PENALTY (Effective Rate Method)
    # =====================================================
    penalty = 0
    overdue_days = 0
    
    if today > overdue_date:
        # Overdue amount = Principal (in bullet loans)
        overdue_amount = principal
        overdue_days = (today - overdue_date).days
        
        # ✅ CORRECT FORMULA: Penalty on overdue principal with effective rate
        effective_rate = rate + penalty_rate
        penalty = (overdue_amount * effective_rate * overdue_days) / (100 * 365)
        penalty = round(penalty, 2)
    
    # =====================================================
    # PAYMENT ALLOCATION: Penalty → Interest → Principal
    # =====================================================
    
    # 1. Pay penalty first
    penalty_paid_now = min(remaining, penalty)
    remaining -= penalty_paid_now
    
    # 2. Pay interest (accrued from start date)
    interest_paid = min(remaining, total_interest)
    remaining -= interest_paid
    
    interest_balance = total_interest - interest_paid
    
    # 3. Pay principal (only if interest fully paid)
    principal_paid = 0
    if interest_balance == 0 and remaining > 0:
        principal_paid = min(remaining, principal)
        remaining -= principal_paid
        principal -= principal_paid
        
        # Update loan principal in loans collection
        loans_collection.update_one(
            {"_id": ObjectId(loan_id)},
            {"$set": {"loan_amount": round(principal, 2)}}
        )
    
    # =====================================================
    # DAYS COVERED CALCULATION
    # =====================================================
    days_covered = 0
    if daily_interest > 0 and interest_paid > 0:
        days_covered_float = interest_paid / daily_interest
        days_covered = int(days_covered_float)
    
    # =====================================================
    # DATE SHIFT LOGIC
    # =====================================================
    if interest_balance == 0:
        # Full interest paid - reset cycle
        new_interest_start = today
        new_overdue_date = today + relativedelta(months=tenure_months)
    else:
        # Partial interest paid - shift forward
        new_interest_start = interest_start + timedelta(days=days_covered)
        new_overdue_date = overdue_date + timedelta(days=days_covered)
        
        if new_interest_start > today:
            new_interest_start = today
    
    # MATURITY LIMIT CHECK
    if new_overdue_date > maturity_date:
        new_overdue_date = maturity_date
    
    # =====================================================
    # RECALCULATE DAILY INTEREST
    # =====================================================
    if principal > 0:
        new_daily_interest = (principal * rate) / (100 * days_in_year)
    else:
        new_daily_interest = 0
    
    # =====================================================
    # FINAL PENDING CALCULATION
    # =====================================================
    new_penalty_remaining = penalty - penalty_paid_now
    pending = principal + interest_balance + new_penalty_remaining
    
    # =====================================================
    # UPDATE CURRENT DUE STATUS
    # =====================================================
    new_penalty_paid_total = due.get("penalty_paid", 0) + penalty_paid_now
    
    loan_dues_collection.update_one(
        {"_id": due["_id"]},
        {"$set": {
            "status": "paid",
            "paid_date": today,
            "interest_paid": round(interest_paid, 2),
            "principal_paid": round(principal_paid, 2),
            "penalty_paid": round(new_penalty_paid_total, 2),
            "penalty_due": penalty,  # Store calculated penalty
            "days_covered": days_covered,
            "total_days": days,
            "overdue_days": overdue_days,
            "pending_amount": round(pending, 2),
            "effective_rate_applied": rate + penalty_rate
        }}
    )
    
    # =====================================================
    # LOAN CLOSURE CHECK
    # =====================================================
    if principal <= 0 and interest_balance <= 0 and new_penalty_remaining <= 0:
        loans_collection.update_one(
            {"_id": ObjectId(loan_id)},
            {"$set": {
                "status": "closed",
                "closed_date": today
            }}
        )
        
        # Mark any remaining dues as paid
        loan_dues_collection.update_many(
            {"loan_id": ObjectId(loan_id), "status": "active"},
            {"$set": {
                "status": "paid",
                "paid_date": today
            }}
        )
        
        create_transactions(
            loan, loan_id, payment_mode,
            interest_paid, principal_paid, penalty_paid_now, 0
        )
        
        return {
            "type": "BULLET",
            "message": "Loan Closed Successfully",
            "interest_paid": round(interest_paid, 2),
            "principal_paid": round(principal_paid, 2),
            "penalty_paid": round(penalty_paid_now, 2),
            "overdue_days": overdue_days,
            "effective_rate": round(rate + penalty_rate, 2),
            "loan_status": "closed"
        }
    
    # =====================================================
    # CREATE NEXT DUE (If loan still active)
    # =====================================================
    next_due = {
        "loan_id": due["loan_id"],
        "loan_no": due["loan_no"],
        "customer_id": due["customer_id"],
        "customer_name": due["customer_name"],
        "customer_code": due.get("customer_code"),
        
        # Principal details
        "principal": round(principal, 2),
        "interest_rate": rate,
        "interest_for_oneday": round(new_daily_interest, 4),
        
        # Dates
        "loan_start_date": due.get("loan_start_date"),
        "interest_start_date": new_interest_start,
        "overdue_date": new_overdue_date,
        "maturity_date": maturity_date,
        
        # Interest tracking
        "interest_due": round(interest_balance, 2),
        "interest_paid": 0,
        "principal_paid": 0,
        
        # Penalty tracking for next cycle
        "penalty_due": 0,
        "penalty_paid": 0,
        "penalty_rate_applied": penalty_rate,
        "effective_rate_applied": rate + penalty_rate,
        "overdue_days": 0,
        "last_penalty_update": None,
        
        # Status
        "pending_amount": round(pending, 2),
        "status": "active",
        "created_at": today
    }
    
    loan_dues_collection.insert_one(next_due)
    
    # =====================================================
    # CREATE TRANSACTION RECORDS
    # =====================================================
    create_transactions(
        loan,
        loan_id,
        payment_mode,
        interest_paid,
        principal_paid,
        penalty_paid_now,
        0
    )
    
    # =====================================================
    # RESPONSE WITH ALL DETAILS
    # =====================================================
    return {
        "type": "BULLET",
        "scenario": get_payment_scenario(interest_paid, total_interest, principal_paid, penalty_paid_now),
        "interest_paid": round(interest_paid, 2),
        "principal_paid": round(principal_paid, 2),
        "penalty_paid": round(penalty_paid_now, 2),
        "interest_remaining": round(interest_balance, 2),
        "principal_remaining": round(principal, 2),
        "penalty_remaining": round(new_penalty_remaining, 2),
        "days_covered": days_covered,
        "total_days": days,
        "overdue_days": overdue_days,
        "effective_rate": round(rate + penalty_rate, 2),
        "daily_interest_rate": round(daily_interest, 4),
        "new_daily_interest": round(new_daily_interest, 4),
        "old_interest_start": interest_start,
        "new_interest_start": new_interest_start,
        "old_overdue_date": overdue_date,
        "new_overdue_date": new_overdue_date,
        "maturity_date": maturity_date,
        "pending": round(pending, 2),
        "loan_status": "active",
        "message": get_payment_message(interest_paid, total_interest, principal_paid, days)
    }


def get_payment_scenario(interest_paid, total_interest, principal_paid, penalty_paid):
    """
    Determine which payment scenario occurred
    """
    if penalty_paid > 0:
        return "OVERDUE_PAYMENT_WITH_PENALTY"
    elif interest_paid == total_interest and principal_paid == 0:
        return "SCENARIO_1: FULL_INTEREST_PAID"
    elif interest_paid == total_interest and principal_paid > 0:
        return "SCENARIO_2: INTEREST_PLUS_PRINCIPAL_REDUCTION"
    elif 0 < interest_paid < total_interest and principal_paid == 0:
        return "SCENARIO_3: PARTIAL_INTEREST_PAID"
    elif interest_paid > 0 and interest_paid < total_interest:
        return "SCENARIO_4: SMALL_PAYMENT_COVERS_PARTIAL_DAYS"
    elif interest_paid == 0 and principal_paid > 0:
        return "SCENARIO_5: DIRECT_PRINCIPAL_REDUCTION_NO_INTEREST"
    else:
        return "REGULAR_PAYMENT"


def get_payment_message(interest_paid, total_interest, principal_paid, days):
    """
    Generate user-friendly message
    """
    if days == 1 and interest_paid > 0:
        return f"Payment on Day 1: ₹{interest_paid} interest paid for 1 day + ₹{principal_paid} principal reduction."
    elif days == 1 and principal_paid > 0:
        return f"Payment on Day 1: ₹{principal_paid} principal reduced. Future interest will be lower."
    elif interest_paid == total_interest and principal_paid > 0:
        return f"Paid ₹{interest_paid} interest for {days} days + ₹{principal_paid} principal reduction."
    elif interest_paid == total_interest:
        return f"Paid full interest of ₹{interest_paid} for {days} days. Loan timeline reset."
    elif interest_paid > 0 and interest_paid < total_interest:
        days_covered = int(interest_paid / (total_interest / days))
        return f"Paid ₹{interest_paid} interest covering {days_covered} out of {days} days. Remaining interest continues."
    else:
        return "Payment processed successfully."