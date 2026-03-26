from math import pow
from datetime import datetime, timedelta

# =========================
# EMI CALCULATION
# =========================
def calculate_emi(principal: float, annual_rate: float, tenure: int):

    monthly_rate = annual_rate / 12 / 100

    emi = (
        principal
        * monthly_rate
        * pow(1 + monthly_rate, tenure)
        / (pow(1 + monthly_rate, tenure) - 1)
    )

    return round(emi, 2)


# =========================
# EMI SCHEDULE GENERATION
# =========================
def generate_emi_schedule(principal, annual_rate, tenure, start_date):

    monthly_rate = annual_rate / 12 / 100
    emi = calculate_emi(principal, annual_rate, tenure)

    balance = principal
    schedule = []

    for i in range(1, tenure + 1):

        interest = balance * monthly_rate
        principal_paid = emi - interest
        balance -= principal_paid

        if balance < 0:
            principal_paid += balance
            balance = 0

        due_date = start_date + timedelta(days=30 * i)

        schedule.append({
            "installment_no": i,
            "emi_amount": round(emi, 2),
            "interest_due": round(interest, 2),
            "principal_due": round(principal_paid, 2),
            "balance_amount": round(balance, 2),
            "due_date": due_date,
            "status": "pending"
        })

    return schedule