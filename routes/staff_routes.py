from datetime import datetime
from bson import ObjectId
from fastapi import APIRouter, Depends
from database.db import staffs_collection
from schemas.staff import StaffSchema, StaffUpdate
from utils.auth import admin_required

router = APIRouter(prefix="/staff", tags=["staffs"])

@router.post("/staff/create")
def create_customer(data: StaffSchema, user=Depends(admin_required)):

    staff_dict = data.dict()

    
    staff_dict["dob"] = datetime.combine(data.dob, datetime.min.time())
    staff_dict["status"] = "active"
    

    staff_dict["created_by"] = user["role"]

    staff_dict["created_at"] = datetime.utcnow()
    staff_dict["updated_at"] = datetime.utcnow()
    staff_dict["role"] = "staff"

    staffs_collection.insert_one(staff_dict)

    return {"message": "staff created successfully"}




@router.put("/staff/update/{id}")
def update_staff(id: str, data: StaffUpdate, user=Depends(admin_required)):

    update_data = data.model_dump(exclude_none=True)

    # Convert DOB to datetime if present
    if "dob" in update_data:
        update_data["dob"] = datetime.combine(update_data["dob"], datetime.min.time())

    update_data["updated_at"] = datetime.utcnow()

    staffs_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": update_data}
    )

    return {"message": "Staff updated successfully"}

@router.get("/staff/{id}")
def get_staff(id: str, user=Depends(admin_required)):          

    staff = staffs_collection.find_one({"_id": ObjectId(id)})

    if not staff:
        return {"message": "Staff not found"}

    staff["_id"] = str(staff["_id"])

    return staff

@router.get("/staffs/active")
def get_active_staffs(user=Depends(admin_required)):    

    staffs = list(
        staffs_collection.find({"status": "active"})
    )

    for staff in staffs:
        staff["id"] = str(staff["_id"])
        del staff["_id"]

    return staffs

@router.get("/staffs/inactive")
def get_inactive_staffs(user=Depends(admin_required)):    

    staffs = list(
        staffs_collection.find({"status": "inactive"})
    )

    for staff in staffs:
        staff["id"] = str(staff["_id"])
        del staff["_id"]

    return staffs



@router.delete("/staff-deletion/{id}")
def delete_staff(id: str, user=Depends(admin_required)):

    staffs_collection.update_one(
        {"_id": ObjectId(id)},
        {
            "$set": {
                "status": "inactive",
                "updated_at": datetime.utcnow()
            }
        }
    )

    return {"message": "Staff set to inactive"}