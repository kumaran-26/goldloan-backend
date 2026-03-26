# scheduler.py - UPDATED WITH CONDITIONAL CHECK

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
from bson import ObjectId
import atexit
import logging
from database.db import (
    loans_collection,
    transactions_collection,
    loan_dues_collection,
    scheme_collection
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def is_leap_year(date):
    y = date.year
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)

def calculate_daily_penalty(principal, penalty_rate, days_overdue):
    """
    Calculate penalty for overdue loan - BANK STANDARD
    Penalty on Principal ONLY (not on interest)
    """
    if principal <= 0 or penalty_rate <= 0 or days_overdue <= 0:
        return 0
    
    days_in_year = 366 if is_leap_year(datetime.utcnow()) else 365
    penalty = (principal * penalty_rate * days_overdue) / (100 * days_in_year)
    return round(penalty, 2)

def add_penalty_fields_if_overdue(due):
    """
    Check if overdue date is before today, then add penalty fields
    Returns: (is_overdue, updates_needed)
    """
    today = datetime.utcnow()
    overdue_date = due.get("overdue_date")
    
    # Check if overdue date exists and is before today
    if not overdue_date:
        return False, {}
    
    is_overdue = today > overdue_date
    
    if not is_overdue:
        return False, {}
    
    # Only add fields if loan is overdue
    updates = {}
    fields_to_add = []
    
    if "penalty_due" not in due:
        updates["penalty_due"] = 0
        fields_to_add.append("penalty_due")
    
    if "overdue_days" not in due:
        updates["overdue_days"] = 0
        fields_to_add.append("overdue_days")
    
    if "last_penalty_update" not in due:
        updates["last_penalty_update"] = None
        fields_to_add.append("last_penalty_update")
    
    if "penalty_rate_applied" not in due:
        updates["penalty_rate_applied"] = 0
        fields_to_add.append("penalty_rate_applied")
    
    if fields_to_add:
        logger.info(f"Loan {due['loan_no']} is overdue - Adding missing fields: {fields_to_add}")
    
    return True, updates

def update_overdue_penalties():
    """
    Daily job to calculate and update penalties for all overdue loans
    """
    today = datetime.utcnow()
    logger.info(f"[SCHEDULER] Running penalty update at {today}")
    
    try:
        # Find all active loan dues
        all_active_dues = list(loan_dues_collection.find({
            "status": "active"
        }))
        
        if not all_active_dues:
            logger.info("No active loans found")
            return
        
        updated_count = 0
        penalty_added_total = 0
        field_added_count = 0
        
        for due in all_active_dues:
            try:
                # Check if loan is overdue and add fields if needed
                is_overdue, field_updates = add_penalty_fields_if_overdue(due)
                
                if not is_overdue:
                    # Skip non-overdue loans
                    continue
                
                # Add missing fields first
                if field_updates:
                    loan_dues_collection.update_one(
                        {"_id": due["_id"]},
                        {"$set": field_updates}
                    )
                    field_added_count += 1
                    # Refresh due with new fields
                    due = loan_dues_collection.find_one({"_id": due["_id"]})
                
                # Get loan details for penalty rate
                loan = loans_collection.find_one({"_id": due["loan_id"]})
                if not loan:
                    logger.warning(f"Loan not found for due ID: {due['_id']}")
                    continue
                
                # Get scheme for penalty rate
                scheme = scheme_collection.find_one({"_id": loan.get("scheme_id")})
                if not scheme:
                    logger.warning(f"Scheme not found for loan: {due['loan_no']}")
                    continue
                
                penalty_rate = scheme.get("penalty_percent", 0)
                if penalty_rate == 0:
                    logger.info(f"No penalty rate for loan {due['loan_no']}")
                    continue
                
                # Calculate days overdue
                overdue_date = due["overdue_date"]
                days_overdue = (today - overdue_date).days
                
                if days_overdue <= 0:
                    continue
                
                # Calculate principal amount
                principal = due.get("principal", 0)
                
                # Calculate penalty (BANK STANDARD - on principal only)
                penalty_amount = calculate_daily_penalty(principal, penalty_rate, days_overdue)
                
                # Get existing penalty due
                existing_penalty_due = due.get("penalty_due", 0)
                
                # Update penalty if increased
                if penalty_amount > existing_penalty_due:
                    # Update penalty due
                    loan_dues_collection.update_one(
                        {"_id": due["_id"]},
                        {"$set": {
                            "penalty_due": penalty_amount,
                            "overdue_days": days_overdue,
                            "last_penalty_update": today,
                            "penalty_rate_applied": penalty_rate
                        }}
                    )
                    
                    penalty_diff = penalty_amount - existing_penalty_due
                    penalty_added_total += penalty_diff
                    updated_count += 1
                    
                    logger.info(f"✅ Updated penalty for {due['loan_no']}: ₹{penalty_amount} "
                              f"({days_overdue} days overdue, added: ₹{penalty_diff})")
                    
                    # Create transaction record for penalty addition
                    create_penalty_transaction(due, penalty_diff, days_overdue, today)
                else:
                    # Just update overdue days if penalty hasn't increased
                    loan_dues_collection.update_one(
                        {"_id": due["_id"]},
                        {"$set": {
                            "overdue_days": days_overdue,
                            "last_penalty_update": today
                        }}
                    )
                    logger.info(f"📝 Updated overdue days for {due['loan_no']}: {days_overdue} days")
                
            except Exception as e:
                logger.error(f"Error updating penalty for due {due['_id']}: {str(e)}")
                continue
        
        logger.info(f"[SCHEDULER] Completed:")
        logger.info(f"   - Added penalty fields to: {field_added_count} overdue loans")
        logger.info(f"   - Updated penalties for: {updated_count} loans")
        logger.info(f"   - Total penalty added: ₹{penalty_added_total}")
        
    except Exception as e:
        logger.error(f"[SCHEDULER] Error in penalty update: {str(e)}")

def create_penalty_transaction(due, penalty_added, days_overdue, update_date):
    """
    Create a transaction record for auto-added penalty
    """
    try:
        # Check if penalty already added today (avoid duplicates)
        today_start = update_date.replace(hour=0, minute=0, second=0, microsecond=0)
        
        existing = transactions_collection.find_one({
            "loan_id": due["loan_id"],
            "payment_type": "penalty_auto_added",
            "transaction_date": {"$gte": today_start}
        })
        
        if existing:
            logger.info(f"Penalty already added today for {due['loan_no']}")
            return
        
        # Insert penalty transaction
        transactions_collection.insert_one({
            "loan_id": due["loan_id"],
            "loan_no": due["loan_no"],
            "customer_id": due.get("customer_id"),
            "customer_name": due.get("customer_name"),
            "transaction_type": "debit",
            "payment_type": "penalty_auto_added",
            "amount": round(penalty_added, 2),
            "total_penalty_due": round(due.get("penalty_due", 0) + penalty_added, 2),
            "overdue_days": days_overdue,
            "transaction_date": update_date,
            "created_at": update_date,
            "notes": f"Auto penalty added for {days_overdue} days overdue"
        })
        
        logger.info(f"Created penalty transaction for {due['loan_no']}: ₹{penalty_added}")
        
    except Exception as e:
        logger.error(f"Error creating penalty transaction: {str(e)}")

def start_scheduler():
    """Start the background scheduler"""
    
    # Run at midnight every day
    scheduler.add_job(
        update_overdue_penalties,
        trigger=CronTrigger(hour=0, minute=0),  # Runs at 00:00 daily
        id="daily_penalty_update",
        name="Daily Penalty Update Job",
        replace_existing=True
    )
    
    # Run immediately on startup to check current overdue loans
    scheduler.add_job(
        update_overdue_penalties,
        trigger='date',
        run_date=datetime.now() + timedelta(seconds=5),
        id="startup_penalty_update",
        name="Startup Penalty Update"
    )
    
    scheduler.start()
    logger.info("✅ Scheduler started successfully - Daily penalty update enabled")
    
    # Log next run time
    next_run = scheduler.get_job("daily_penalty_update").next_run_time
    logger.info(f"Next penalty update scheduled at: {next_run}")

def shutdown_scheduler():
    """Shutdown the scheduler on app exit"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler shutdown successfully")

# Register shutdown handler
atexit.register(shutdown_scheduler)