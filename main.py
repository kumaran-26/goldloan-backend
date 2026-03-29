# main.py
import sys
import asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from contextlib import asynccontextmanager

from routes import auth_routes
from routes import disburse_routes
from routes import loan_routes
from routes import scheme_routes
from routes import gold_rate_routes
from routes import customer_routes
from routes import staff_routes

from routes import transaction_routes

# Import scheduler
from utils.schedular import start_scheduler, shutdown_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Starting Gold Loan Management System...")
    start_scheduler()  # Start the background scheduler
    yield
    # Shutdown
    print("Shutting down...")
    shutdown_scheduler()

app = FastAPI(
    title="Gold Loan Management System",
    lifespan=lifespan  # Use lifespan for startup/shutdown events
)

# Include all routers
app.include_router(auth_routes.router)
app.include_router(customer_routes.router)
app.include_router(staff_routes.router)
app.include_router(loan_routes.router)
app.include_router(scheme_routes.router)
app.include_router(gold_rate_routes.router)
app.include_router(disburse_routes.router)  

app.include_router(transaction_routes.router)

