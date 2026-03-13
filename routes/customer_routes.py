from datetime import datetime
from bson import ObjectId
from fastapi import APIRouter, Depends
from database.db import customers_collection
from schemas.customer import CustomerSchema, CustomerUpdate
from utils.auth import admin_or_staff_required,admin_required

router = APIRouter(prefix="/customers", tags=["customers"])

@router.post("/customer/create")
def create_customer(data: CustomerSchema, user=Depends(admin_or_staff_required)):

    customer_dict = data.dict()

    customer_dict["dob"] = datetime.combine(data.dob, datetime.min.time())
   
   
    customer_dict["status"] = "active"

    customer_dict["created_by"] = user["role"]

    customer_dict["created_at"] = datetime.utcnow()
    customer_dict["updated_at"] = datetime.utcnow()

    customers_collection.insert_one(customer_dict)

    return {"message": "Customer created successfully"}



@router.put("/customer/update/{id}")
def update_customer(id: str, data: CustomerUpdate, user=Depends(admin_or_staff_required)):

    update_data = {k: v for k, v in data.dict(exclude_none=True).items()}

    if "dob" in update_data:
        update_data["dob"] = datetime.combine(update_data["dob"], datetime.min.time())

    update_data["updated_at"] = datetime.utcnow()

    customers_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": update_data}
    )

    return {"message": "Customer updated successfully"}

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