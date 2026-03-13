from pymongo import MongoClient


client = MongoClient("mongodb://localhost:27017")

db = client["goldloan_db"]

users_collection = db["users"]
customers_collection = db["customers"]
scheme_collection = db["schemes"]
loans_collection = db["loans"]
gold_rates_loans_collection = db["gold_rates_loans"]
historyloans_collection = db["historyloans"]
staffs_collection = db["staff"]
gold_collection=db["gold"]
disbursements_collection = db["disbursements"]


