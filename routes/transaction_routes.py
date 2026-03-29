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
    INCLUDING the end date
    """
    if not start_date or not end_date:
        return 0
    
    delta = (end_date - start_date).days + 1
    return delta


def calculate_interest(principal, rate, start_date, end_date):
    """
    Calculate total interest for a period using actual days
    INCLUDES both start and end dates
    Returns: (interest_amount, days)
    """
    if not start_date or not end_date:
        return 0, 0
    
    days = calculate_actual_days(start_date, end_date)
    if days <= 0:
        return 0, 0
    
    days_in_year = get_days_in_year(end_date)
    interest = (principal * rate * days) / (100 * days_in_year)
    return round(interest, 2), days


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
    """Calculate next due date with proper month-end handling"""
    due_date = start_date + relativedelta(months=tenure_months)
    return validate_date(due_date)


def calculate_grace_period_end_date(due_date, grace_days):
    """
    Calculate the end date of grace period
    Grace period end = due_date + grace_days
    """
    if not due_date or grace_days <= 0:
        return due_date
    
    return due_date + timedelta(days=grace_days)


def calculate_total_overdue_days(due_date, current_date=None):
    """
    Calculate total overdue days INCLUDING all days from due date
    This counts EVERY day from due date to current date (inclusive)
    """
    if current_date is None:
        current_date = datetime.utcnow()
    
    if not due_date:
        return 0
    
    if current_date <= due_date:
        return 0
    
    total_overdue_days = calculate_actual_days(due_date, current_date)
    return total_overdue_days


def calculate_penalty(interest_due, penalty_rate, due_date, current_date=None):
    """
    Calculate penalty based on total overdue days INCLUDING grace period
    Penalty applies to ALL overdue days including grace period
    """
    if current_date is None:
        current_date = datetime.utcnow()
    
    overdue_days = calculate_total_overdue_days(due_date, current_date)
    
    if overdue_days <= 0 or interest_due <= 0 or penalty_rate <= 0:
        return 0, overdue_days
    
    penalty = (interest_due * penalty_rate * overdue_days) / (100 * 365)
    return round(penalty, 2), overdue_days


def calculate_penalty_with_grace(interest_due, penalty_rate, due_date, grace_days, current_date=None):
    """
    Calculate penalty considering grace period
    Penalty applies only to days AFTER grace period
    
    Formula: Penalty = (Interest Due × Penalty Rate × Overdue Days) / (365 × 100)
    """
    if current_date is None:
        current_date = datetime.utcnow()
    
    # Calculate grace period end date
    grace_end_date = calculate_grace_period_end_date(due_date, grace_days)
    
    # Calculate overdue days after grace period
    if current_date <= grace_end_date:
        overdue_days = 0
    else:
        overdue_days = (current_date - grace_end_date).days
    
    if overdue_days <= 0 or interest_due <= 0 or penalty_rate <= 0:
        return 0, overdue_days
    
    penalty = (interest_due * penalty_rate * overdue_days) / (100 * 365)
    return round(penalty, 2), overdue_days


def calculate_days_covered_by_interest(interest_paid, daily_interest, max_days=None):
    """
    Calculate how many days are covered by interest payment
    """
    if daily_interest <= 0 or interest_paid <= 0:
        return 0
    
    days_covered = int(interest_paid / daily_interest)
    
    if max_days and days_covered > max_days:
        days_covered = max_days
    
    if days_covered == 0 and interest_paid > 0:
        days_covered = 1
    
    return days_covered


# =====================================================
# MAIN API
# =====================================================

@router.post("/pay/{loan_id}", dependencies=[Depends(admin_required)])
def pay_loan(
    loan_id: str, 
    amount: float, 
    payment_mode: str = "cash"
):
    """
    Process loan payment
    Interest accrues for ALL days including grace period
    Overdue includes grace period days for penalty calculation
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
# BULLET PAYMENT HANDLER
# =====================================================

def handle_bullet_payment(loan, scheme, loan_id, amount, payment_mode):
    """
    Complete bullet loan payment handler with grace period support
    """
    today = datetime.utcnow()
    remaining = amount
    
    total_interest_paid = 0
    total_principal_paid = 0
    total_penalty_paid = 0
    
    # GET CURRENT ACTIVE DUE
    due = loan_dues_collection.find_one(
        {"loan_id": ObjectId(loan_id), "status": {"$in": ["pending", "active"]}},
        sort=[("created_at", -1)]
    )
    
    if not due:
        raise HTTPException(status_code=400, detail="No pending due found")
    
    # Get current loan details
    principal = due.get("principal", 0)
    rate = due.get("interest_rate", 0)
    penalty_rate = due.get("penalty_rate", scheme.get("penalty_percent", 0))
    grace_days = due.get("grace_days", scheme.get("grace_speed", 0))  # Use grace_speed from scheme
    tenure_months = scheme.get("tenure_months", 1)
    total_tenure_months = scheme.get("total_tenure_months", 24)
    maturity_date = due.get("maturity_date")
    
    # Get dates
    interest_start = due.get("interest_start_date")
    regular_due_date = due.get("due_date")
    
    # =====================================================
    # STEP 1: Calculate Interest for ACTUAL DAYS
    # =====================================================
    total_interest, days = calculate_interest(principal, rate, interest_start, today)
    
    if days < 1:
        days = 1
    
    # Calculate daily interest
    daily_interest = total_interest / days if days > 0 else 0
    
    # =====================================================
    # STEP 2: Calculate Penalty ONLY on Overdue Days AFTER Grace
    # =====================================================
    penalty_amount, overdue_days = calculate_penalty_with_grace(
        total_interest, 
        penalty_rate, 
        regular_due_date, 
        grace_days, 
        today
    )
    
    # Get existing penalty paid
    penalty_paid_already = due.get("penalty_paid", 0)
    penalty_due = max(0, penalty_amount - penalty_paid_already)
    
    # =====================================================
    # STEP 3: Payment Priority (Penalty → Interest → Principal)
    # =====================================================
    
    # Pay penalty first
    penalty_paid_now = min(remaining, penalty_due)
    remaining -= penalty_paid_now
    total_penalty_paid = penalty_paid_now
    
    # Pay interest
    interest_paid = min(remaining, total_interest)
    remaining -= interest_paid
    total_interest_paid = interest_paid
    
    interest_balance = total_interest - interest_paid
    
    # Pay principal (only if interest fully paid)
    principal_paid = 0
    if interest_balance == 0 and remaining > 0:
        principal_paid = min(remaining, principal)
        remaining -= principal_paid
        principal -= principal_paid
        total_principal_paid = principal_paid
        
        loans_collection.update_one(
            {"_id": ObjectId(loan_id)},
            {"$set": {"loan_amount": round(principal, 2)}}
        )
    
    # =====================================================
    # STEP 4: Calculate Days Covered by Interest Payment
    # =====================================================
    days_covered = 0
    if daily_interest > 0 and interest_paid > 0:
        days_covered_float = interest_paid / daily_interest
        days_covered = int(days_covered_float)
        
        if days_covered == 0 and interest_paid > 0:
            days_covered = 1
    
    # =====================================================
    # STEP 5: Calculate Regular Cycle Days
    # =====================================================
    regular_cycle_days = 0
    if regular_due_date and interest_start:
        regular_cycle_days = calculate_actual_days(interest_start, regular_due_date)
    
    # =====================================================
    # STEP 6: Determine New Interest Start and Due Dates
    # =====================================================
    new_interest_start = interest_start
    new_regular_due_date = regular_due_date
    
    # Calculate next cycle's interest amount
    next_interest_due = 0
    
    if interest_balance == 0:
        # Full interest paid for the period
        if days_covered > regular_cycle_days and regular_cycle_days > 0:
            # Paid for more days than the cycle - carry forward extra days
            extra_days = days_covered - regular_cycle_days
            new_interest_start = regular_due_date + timedelta(days=extra_days)
            new_interest_start = validate_date(new_interest_start)
            new_regular_due_date = new_interest_start + relativedelta(months=tenure_months)
        else:
            # Normal case - start new cycle from today
            new_interest_start = today
            new_regular_due_date = today + relativedelta(months=tenure_months)
        
        # Calculate interest for the next cycle
        if principal > 0:
            # Calculate days in next cycle
            next_cycle_days = calculate_actual_days(new_interest_start, new_regular_due_date)
            if next_cycle_days < 1:
                next_cycle_days = 1
            
            # Calculate total interest for next cycle
            next_interest_due = calculate_interest_for_period(principal, rate, new_interest_start, new_regular_due_date)
        else:
            next_interest_due = 0
            
    else:
        # Partial interest paid - shift dates by days covered
        new_interest_start = interest_start + timedelta(days=days_covered)
        new_regular_due_date = regular_due_date + timedelta(days=days_covered)
        
        # Don't let new_interest_start go beyond today
        if new_interest_start > today:
            new_interest_start = today
        
        # For partial payment, the remaining interest is carried forward
        next_interest_due = interest_balance
    
    new_interest_start = validate_date(new_interest_start)
    new_regular_due_date = validate_date(new_regular_due_date)
    
    # =====================================================
    # STEP 7: Apply Maturity Limit
    # =====================================================
    if new_regular_due_date > maturity_date:
        new_regular_due_date = maturity_date
    
    # =====================================================
    # STEP 8: Check if this is the final cycle
    # =====================================================
    current_cycle = due.get("cycle_number", 1)
    total_cycles = due.get("total_cycles", (total_tenure_months // tenure_months) if tenure_months > 0 else 1)
    is_final_cycle = False
    
    if new_regular_due_date >= maturity_date:
        is_final_cycle = True
        # For final cycle, include principal in due
        next_interest_due = next_interest_due + principal
    elif new_regular_due_date + relativedelta(months=tenure_months) > maturity_date:
        # Next cycle would go beyond maturity, so this is the last interest cycle
        is_final_cycle = True
        # Adjust due date to maturity date
        new_regular_due_date = maturity_date
        # Recalculate interest for final period
        if principal > 0 and new_interest_start:
            next_interest_due = calculate_interest_for_period(principal, rate, new_interest_start, new_regular_due_date)
    
    # =====================================================
    # STEP 9: Check Auction Logic
    # =====================================================
    loan_status = "active"
    if today >= maturity_date and principal > 0:
        loan_status = "auction_pending"
        loans_collection.update_one(
            {"_id": ObjectId(loan_id)},
            {"$set": {"status": "auction_pending"}}
        )
    
    # =====================================================
    # STEP 10: Final Pending Calculation
    # =====================================================
    new_penalty_remaining = penalty_due - penalty_paid_now
    
    # For current due, pending is principal + interest_balance + penalty
    pending_current = principal + interest_balance + new_penalty_remaining
    
    # =====================================================
    # STEP 11: Update Current Due Status
    # =====================================================
    new_penalty_paid_total = due.get("penalty_paid", 0) + penalty_paid_now
    
    # Calculate grace end date for display
    grace_end_date = calculate_grace_period_end_date(regular_due_date, grace_days)
    
    loan_dues_collection.update_one(
        {"_id": due["_id"]},
        {"$set": {
            "status": "paid",
            "paid_date": today,
            "interest_paid": round(interest_paid, 2),
            "principal_paid": round(principal_paid, 2),
            "penalty_paid": round(new_penalty_paid_total, 2),
            "penalty_due": round(penalty_amount, 2),
            "days_calculated": days,
            "days_covered": days_covered,
            "regular_cycle_days": regular_cycle_days,
            "paid_days": days_covered,
            "extra_days_carried": max(0, days_covered - regular_cycle_days) if regular_cycle_days > 0 else 0,
            "overdue_days_after_grace": overdue_days,
            "grace_days": grace_days,
            "grace_end_date": grace_end_date,
            "within_grace": overdue_days == 0,
            "pending_amount": round(pending_current, 2)
        }}
    )
    
    # =====================================================
    # STEP 12: Check Full Loan Closure
    # =====================================================
    if (principal <= 0 or is_final_cycle) and interest_balance <= 0 and new_penalty_remaining <= 0:
        loans_collection.update_one(
            {"_id": ObjectId(loan_id)},
            {"$set": {
                "status": "closed",
                "closed_date": today
            }}
        )
        
        create_transactions(
            loan, loan_id, payment_mode,
            total_interest_paid, total_principal_paid, total_penalty_paid, 0
        )
        
        return {
            "type": "BULLET",
            "message": "Loan Closed Successfully",
            "scenario": "FULL_LOAN_CLOSURE",
            "interest_paid": round(total_interest_paid, 2),
            "principal_paid": round(total_principal_paid, 2),
            "penalty_paid": round(total_penalty_paid, 2),
            "grace_days": grace_days,
            "overdue_days_after_grace": overdue_days,
            "within_grace": overdue_days == 0,
            "loan_status": "closed"
        }
    
    # =====================================================
    # STEP 13: Create Next Due if Loan Not Closed
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
        
        # Calculate daily interest for next cycle
        "interest_per_day": round(calculate_daily_interest(principal, rate, new_regular_due_date), 4) if principal > 0 else 0,
        
        # Cycle information
        "cycle_number": current_cycle + 1,
        "total_cycles": total_cycles,
        "is_final_cycle": is_final_cycle,
        
        # Grace period
        "grace_days": grace_days,
        "penalty_rate": penalty_rate,
        
        # Dates
        "loan_start_date": due.get("loan_start_date"),
        "interest_start_date": new_interest_start,
        "due_date": new_regular_due_date,
        "regular_due_date": new_regular_due_date,
        "cycle_end_date_with_grace": calculate_grace_period_end_date(new_regular_due_date, grace_days),
        "maturity_date": maturity_date,
        
        # Interest tracking
        "interest_due": round(next_interest_due, 2),
        "interest_paid": 0,
        "principal_paid": 0,
        
        # Penalty tracking
        "penalty_due": 0,
        "penalty_paid": 0,
        
        # Additional metrics
        "regular_days": calculate_actual_days(new_interest_start, new_regular_due_date),
        "days_in_cycle_with_grace": calculate_actual_days(new_interest_start, calculate_grace_period_end_date(new_regular_due_date, grace_days)),
        
        # Status
        "pending_amount": round(next_interest_due, 2),
        "status": "pending",
        "overdue_days_after_grace": 0,
        "within_grace": True,
        "created_at": today
    }
    
    loan_dues_collection.insert_one(next_due)
    
    # =====================================================
    # STEP 14: Create Transaction Records
    # =====================================================
    create_transactions(
        loan,
        loan_id,
        payment_mode,
        total_interest_paid,
        total_principal_paid,
        total_penalty_paid,
        0
    )
    
    # =====================================================
    # STEP 15: Response with Grace Period Details
    # =====================================================
    return {
        "type": "BULLET",
        "interest_paid": round(total_interest_paid, 2),
        "principal_paid": round(total_principal_paid, 2),
        "penalty_paid": round(total_penalty_paid, 2),
        "interest_remaining": round(interest_balance, 2),
        "principal_remaining": round(principal, 2),
        "penalty_remaining": round(new_penalty_remaining, 2),
        "next_interest_due": round(next_interest_due, 2),
        "days_calculated": days,
        "days_covered": days_covered,
        "grace_days": grace_days,
        "overdue_days_after_grace": overdue_days,
        "within_grace": overdue_days == 0,
        "penalty_rate": penalty_rate,
        "daily_interest": round(daily_interest, 4),
        "new_daily_interest": round(calculate_daily_interest(principal, rate, new_regular_due_date), 4) if principal > 0 else 0,
        "old_interest_start": interest_start,
        "new_interest_start": new_interest_start,
        "old_due_date": regular_due_date,
        "new_due_date": new_regular_due_date,
        "grace_end_date": grace_end_date,
        "new_grace_end_date": calculate_grace_period_end_date(new_regular_due_date, grace_days),
        "maturity_date": maturity_date,
        "current_cycle": current_cycle,
        "next_cycle": current_cycle + 1,
        "is_final_cycle": is_final_cycle,
        "pending": round(pending_current, 2),
        "loan_status": loan_status,
        "message": get_bullet_message_with_grace(
            total_interest_paid, total_interest, total_principal_paid, 
            total_penalty_paid, days_covered, days, 
            overdue_days, grace_days, days_covered, regular_cycle_days, principal,
            penalty_amount, regular_due_date, grace_end_date, next_interest_due
        )
    }


def get_bullet_message_with_grace(interest_paid, total_interest, principal_paid, 
                                   penalty_paid, days_covered, total_days, 
                                   overdue_days, grace_days, paid_days, 
                                   cycle_days, principal_remaining, penalty_amount,
                                   due_date, grace_end_date, next_interest_due):
    """
    Generate user-friendly message with grace period info
    """
    if penalty_paid > 0:
        if overdue_days > 0:
            return f"Payment with penalty. Grace period of {grace_days} days ended on {grace_end_date.strftime('%d-%b-%Y')}. Overdue by {overdue_days} days. Penalty ₹{penalty_paid} applied. Interest ₹{interest_paid} paid."
        else:
            return f"Payment processed. Penalty ₹{penalty_paid} applied."
    
    if overdue_days == 0 and grace_days > 0:
        return f"Payment within {grace_days} days grace period (due date: {due_date.strftime('%d-%b-%Y')}, grace until: {grace_end_date.strftime('%d-%b-%Y')}). No penalty applied. Next interest due: ₹{round(next_interest_due, 2)}"
    
    if interest_paid == total_interest and paid_days > cycle_days and cycle_days > 0:
        extra_days = paid_days - cycle_days
        return f"Paid full interest covering {paid_days} days (current cycle {cycle_days} days + {extra_days} extra days carried forward). Next interest due: ₹{round(next_interest_due, 2)}"
    
    if interest_paid == total_interest:
        if principal_paid > 0:
            return f"Paid full interest ₹{interest_paid} + ₹{principal_paid} principal reduction. Next interest due: ₹{round(next_interest_due, 2)}"
        else:
            return f"Paid full interest ₹{interest_paid}. Reset cycle starting today. Next interest due: ₹{round(next_interest_due, 2)}"
    
    if 0 < interest_paid < total_interest:
        return f"Paid ₹{interest_paid} interest covering {days_covered} out of {total_days} days. Remaining interest: ₹{round(total_interest - interest_paid, 2)}"
    
    if total_days == 1:
        return f"Same day payment: ₹{interest_paid} interest paid. Next interest due: ₹{round(next_interest_due, 2)}"
    
    if interest_paid == 0 and principal_paid > 0:
        return f"Direct principal reduction of ₹{principal_paid}. Next interest due: ₹{round(next_interest_due, 2)}"
    
    return f"Payment processed successfully. Next interest due: ₹{round(next_interest_due, 2)}"


# =====================================================
# EMI PAYMENT HANDLER
# =====================================================

def handle_emi_payment(loan, scheme, loan_id, amount, payment_mode):
    """
    Handle EMI loan payments
    Interest includes grace period days
    Overdue includes grace period days for penalty
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
    
    # Get rates from scheme
    penalty_rate = scheme.get("penalty_percent", 0)
    grace_days = scheme.get("grace_speed", 0)  # Use grace_speed from scheme
    
    total_overdue_days = 0
    
    # Process current EMI and any pending from previous months
    for idx, current_due in enumerate(pending_emis):
        if remaining <= 0:
            break
        
        # Get current EMI details
        interest_due = current_due.get("interest_due", 0) - current_due.get("interest_paid", 0)
        principal_due = current_due.get("principal_due", 0) - current_due.get("principal_paid", 0)
        
        # Get due date and calculate penalty (includes grace days)
        due_date = current_due.get("due_date")
        
        # Calculate penalty based on total overdue days INCLUDING grace days
        penalty_amount, overdue_days = calculate_penalty_with_grace(
            interest_due, 
            penalty_rate, 
            due_date, 
            grace_days, 
            today
        )
        
        total_overdue_days += overdue_days
        
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
            "penalty_due": round(penalty_amount, 2),
            "paid_amount": round(new_paid_amount, 2),
            "pending_amount": round(pending, 2),
            "status": status,
            "last_paid_date": today,
            "overdue_days": overdue_days
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
        
        # Handle excess payment after all EMIs are paid
        if remaining > 0 and idx == len(pending_emis) - 1 and status == "paid":
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
    
    loan_status = "active"
    if pending_dues_count == 0:
        loan_status = "closed"
        loans_collection.update_one(
            {"_id": ObjectId(loan_id)},
            {"$set": {
                "status": "closed",
                "closed_date": datetime.utcnow()
            }}
        )
    
    # Generate message
    message = "Payment processed successfully."
    if total_overdue_days > 0:
        message = f"Payment processed. Overdue by {total_overdue_days} days (including {grace_days} grace days). Penalty ₹{total_penalty_paid} applied."
    elif grace_days > 0:
        message = f"Payment processed within {grace_days} days grace period. No penalty applied."
    
    if pending_dues_count == 0:
        message = "Loan closed successfully! " + message
    
    return {
        "type": "EMI",
        "interest_paid": round(total_interest_paid, 2),
        "principal_paid": round(total_principal_paid, 2),
        "penalty_paid": round(total_penalty_paid, 2),
        "total_paid": round(total_interest_paid + total_principal_paid + total_penalty_paid, 2),
        "pending_emis": pending_dues_count,
        "grace_days": grace_days,
        "total_overdue_days": total_overdue_days,
        "loan_status": loan_status,
        "message": message
    }


# =====================================================
# TRANSACTIONS
# =====================================================

def create_transactions(loan, loan_id, payment_mode,
                        interest_paid, principal_paid, penalty_paid, extra):
    """Create transaction records for payments"""
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
    if extra > 0:
        insert("extra payment", extra)