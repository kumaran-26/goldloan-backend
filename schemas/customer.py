from pydantic import BaseModel, Field, EmailStr
from typing import Literal, Optional
from datetime import date

class AddressSchema(BaseModel):
    address:str
    city: str
    district: str
    pincode: str = Field(..., min_length=6, max_length=6)


class NomineeSchema(BaseModel):
    nominee_name: str
    nominee_relationship: str
    nominee_mobile: str = Field(..., min_length=10, max_length=10)


class KYCSchema(BaseModel):
    aadhaar_number: str = Field(..., min_length=12, max_length=12)
    pan_number: str
    voter_id: str
class CustomerDocuments(BaseModel):

    customer_photo: str
    signature: str

    aadhaar_front: str
    aadhaar_back: str

    pan_card: str

    nominee_photo: str
    nominee_aadhaar: str

class CustomerSchema(BaseModel):

    customer_code: str

    firstname: str
    lastname: str

    mobilenumber: str = Field(..., min_length=10, max_length=10)

    email: EmailStr

    gender: Literal["male", "female",  "other"]

    dob: date

    occupation: str
    monthly_income: float

    address: AddressSchema

    nominee: NomineeSchema

    kyc: KYCSchema
    
    customerdocuments:CustomerDocuments

class AddressUpdate(BaseModel):
    address: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    pincode: Optional[str] = Field(None, min_length=6, max_length=6)

class NomineeUpdate(BaseModel):
    nominee_name: Optional[str] = None
    nominee_relationship: Optional[str] = None
    nominee_mobile: Optional[str] = Field(None, min_length=10, max_length=10)

class KYCUpdate(BaseModel):
    aadhaar_number: Optional[str] = Field(None, min_length=12, max_length=12)
    pan_number: Optional[str] = None
    voter_id: Optional[str] = None

class CustomerDocumentsUpdate(BaseModel):

    customer_photo: Optional[str] = None
    signature: Optional[str] = None

    aadhaar_front: Optional[str] = None
    aadhaar_back: Optional[str] = None

    pan_card: Optional[str] = None

    nominee_photo: Optional[str] = None
    nominee_aadhaar: Optional[str] = None


class CustomerUpdate(BaseModel):

    customer_code: Optional[str] = None

    firstname: Optional[str] = None
    lastname: Optional[str] = None

    mobilenumber: Optional[str] = Field(None, min_length=10, max_length=10)

    email: Optional[EmailStr] = None

    gender: Optional[Literal["male", "female", "other"]] = None

    dob: Optional[date] = None

    occupation: Optional[str] = None
    monthly_income: Optional[float] = None

    address: Optional[AddressUpdate] = None

    nominee: Optional[NomineeUpdate] = None

    kyc: Optional[KYCUpdate] = None

    customerdocuments: Optional[CustomerDocumentsUpdate] = None




