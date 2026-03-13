from jose import jwt
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

SECRET_KEY = "secret123"
ALGORITHM = "HS256"

security = HTTPBearer()

def create_token(data: dict):

    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(hours=12)

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):

    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except:
        raise HTTPException(status_code=401, detail="Invalid Token")


def admin_required(user=Depends(get_current_user)):

    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    return user
def staff_required(user=Depends(get_current_user)):

    if user["role"] != "staff":
        raise HTTPException(status_code=403, detail="Staff only")

    return user 

def admin_or_staff_required(user=Depends(get_current_user)):

    if user["role"] not in ["admin", "staff"]:
        raise HTTPException(status_code=403, detail="Admin or Staff only")

    return user