import sys
import asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI

from routes import auth_routes

from routes import disburse_routes
from routes import loan_routes
from routes import scheme_routes
from routes import gold_routes
from routes import customer_routes
from routes import staff_routes





app = FastAPI(title="Gold Loan Management System")

app.include_router(auth_routes.router)

app.include_router(customer_routes.router)
app.include_router(staff_routes.router)
app.include_router(loan_routes.router)
app.include_router(scheme_routes.router)
app.include_router(gold_routes.router)
app.include_router(disburse_routes.router)  

   # then run every 30 minutes