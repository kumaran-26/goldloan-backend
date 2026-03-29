from datetime import datetime
from bson import ObjectId
from fastapi import APIRouter, Depends
from database.db import customers_collection
from schemas.customer import CustomerSchema, CustomerUpdate
from utils.auth import admin_or_staff_required,admin_required

router = APIRouter(prefix="/customers", tags=["customers"])
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

router = APIRouter()

@router.post("/customer/create")
def create_customer(data: CustomerSchema, user=Depends(admin_or_staff_required)):

    # -------- CHECK DUPLICATE EMAIL --------
    existing_email = customers_collection.find_one({"email": data.email})
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already exists")

    # -------- CHECK DUPLICATE MOBILE --------
    existing_mobile = customers_collection.find_one({"mobilenumber": data.mobilenumber})
    if existing_mobile:
        raise HTTPException(status_code=400, detail="Mobile number already exists")

    # -------- CALCULATE AGE --------
    today = date.today()
    age = relativedelta(today, data.dob).years

    # Optional validation (example: minimum age 18)
    if age < 18:
        raise HTTPException(status_code=400, detail="Customer must be at least 18 years old")

    # -------- CONVERT DATA --------
    customer_dict = data.dict()

    # Convert DOB to datetime
    customer_dict["dob"] = datetime.combine(data.dob, datetime.min.time())

    # Add calculated age
    customer_dict["age"] = age

    # -------- DEFAULT FIELDS --------
    customer_dict["status"] = "active"
    customer_dict["created_by"] = user["role"]
    customer_dict["created_at"] = datetime.utcnow()
    customer_dict["updated_at"] = datetime.utcnow()

    # -------- INSERT --------
    customers_collection.insert_one(customer_dict)

    return {
        "message": "Customer created successfully",
        
    }
@router.get("/customer/{id}")
def get_customer(id: str, user=Depends(admin_or_staff_required)):          

    customer = customers_collection.find_one({"_id": ObjectId(id)})

    if not customer:
        return {"message": "Customer not found"}

    customer["_id"] = str(customer["_id"])

    return customer


@router.get("/customer/inactive")
def get_inactive_schemes(user=Depends(admin_required)):

    customers= list(
        customers_collection.find({"status": "inactive"})
    )

    for customer in customers:
        customer["id"] = str(customer["_id"])
        del customer["_id"]

    return customers

@router.get("/customer/active")
def get_active_customers(user=Depends(admin_required)):

    customers= list(
        customers_collection.find({"status": "active"})
    )

    for customer in customers:
        customer["id"] = str(customer["_id"])
        del customer["_id"]

    return customers


@router.delete("/customer-deletion/{id}")
def delete_customer(id: str, user=Depends(admin_or_staff_required)):

    customers_collection.update_one(
        {"_id": ObjectId(id)},
        {
            "$set": {
                "status": "inactive",
                "updated_at": datetime.utcnow()
            }
        }
    )

    return {"message": "customer set to inactive"}    