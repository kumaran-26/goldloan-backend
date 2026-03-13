from fastapi import APIRouter, HTTPException
from database.db import users_collection,staffs_collection
from schemas.auth import LoginSchema, staffloginSchema
from utils.auth import create_token

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login")


def login(user: LoginSchema):

    db_user = users_collection.find_one({"username": user.username})

    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if db_user["password"] != user.password:
        raise HTTPException(status_code=401, detail="Invalid password")

    token = create_token({
        "id": str(db_user["_id"]),
        "role": db_user["role"]
    })

    return {"access_token": token,
            "role": db_user["role"]
                 }


@router.post("/staff/login")   

def staff_login(user: staffloginSchema):

     db_user = staffs_collection.find_one({"email": user.email})

     if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

     if db_user["password"] != user.password:
        raise HTTPException(status_code=401, detail="Invalid password")

     token = create_token({
        "id": str(db_user["_id"]),
        "role": db_user["role"]
    })

     return {"access_token": token,
            "role": db_user["role"]
                 }


