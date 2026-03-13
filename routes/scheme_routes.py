from fastapi import APIRouter, Depends
from database.db import scheme_collection, customers_collection
from schemas.schemes import SchemeSchema, SchemeUpdate
from utils.auth import admin_required, admin_or_staff_required  
from bson import ObjectId
from datetime import datetime

router = APIRouter(prefix="/schemes", tags=["schemes"])

@router.post("/schemes_create")
def create_scheme(scheme: SchemeSchema,user=Depends(admin_required)):

    scheme_dict = scheme.dict()

    scheme_dict["status"] = "active"
    scheme_dict["created_at"] = datetime.datetime.utcnow()
    scheme_dict["updated_at"] = datetime.datetime.utcnow()

    scheme_collection.insert_one(scheme_dict)

    return {"message": "Scheme created successfully"}




@router.get("/schemes/active")
def get_active_schemes(user=Depends(admin_or_staff_required)):

    schemes = list(
        scheme_collection.find({"status": "active"})
    )

    for scheme in schemes:
        scheme["id"] = str(scheme["_id"])
        del scheme["_id"]

    return schemes



@router.get("/schemes/inactive")
def get_inactive_schemes(user=Depends(admin_required)):

    schemes = list(
        scheme_collection.find({"status": "inactive"})
    )

    for scheme in schemes:
        scheme["id"] = str(scheme["_id"])
        del scheme["_id"]

    return schemes



@router.put("/schemes/{id}")
def update_scheme(id: str, scheme: SchemeUpdate,user=Depends(admin_required)):

    update_data = {k: v for k, v in scheme.dict().items() if v is not None}

    update_data["updated_at"] = datetime.utcnow()

    scheme_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": update_data}
    )

    return {"message": "Scheme updated"}

@router.delete("/schemes/{id}")
def delete_scheme(id: str, user=Depends(admin_required)):

    # check if scheme used by any customer
    customer = customers_collection.find_one({"scheme_id": ObjectId(id)})

    if customer:
        return {"error": "Scheme is assigned to a customer. Cannot deactivate."}

    scheme_collection.update_one(
        {"_id": ObjectId(id)},
        {
            "$set": {
                "status": "inactive",
                "updated_at": datetime.utcnow()
            }
        }
    )

   
    return {"message": "Scheme set to inactive"}

@router.get("/schemes/{id}")
def get_scheme(id: str, user=Depends(admin_required)):  
    scheme = scheme_collection.find_one({"_id": ObjectId(id)})

    if not scheme:
        return {"message": "Scheme not found"}

    scheme["id"] = str(scheme["_id"])
    del scheme["_id"]

    return scheme