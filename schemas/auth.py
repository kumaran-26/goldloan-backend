from pydantic import BaseModel

class LoginSchema(BaseModel):

    username: str
    password: str

class staffloginSchema(BaseModel):

    email: str
    password: str




