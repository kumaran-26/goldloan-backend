from pymongo import MongoClient


client = MongoClient("mongodb://localhost:27017")

db = client["goldloan_db"]

users_collection = db["users"]  #user collection

customers_collection = db["customers"]  #customer collection

scheme_collection = db["schemes"] #scheme collection

loan_dues_collection = db["loan_dues"] #loan dues collection

loans_collection = db["loans"] #loans collection

gold_rate_collection = db["gold_rate"] 

rate_history_collection = db["rate_history"]

staffs_collection = db["staff"]

disbursements_collection = db["disbursements"]

transactions_collection = db["transactions"]

