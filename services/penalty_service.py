from datetime import datetime

def calculate_penalty(emi_amount, penalty_rate, due_date):

    today = datetime.utcnow()

    if today <= due_date:
        return 0, 0

    overdue_days = (today - due_date).days

    # penalty per day
    penalty = (emi_amount * penalty_rate * overdue_days) / (100 * 30)

    return round(penalty, 2), overdue_days