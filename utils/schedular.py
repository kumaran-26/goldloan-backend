from apscheduler.schedulers.background import BackgroundScheduler
from scraper.run_spider import run_spider

scheduler = BackgroundScheduler()

def start_scheduler():
    scheduler.add_job(run_spider, "interval", minutes=30)
    scheduler.start()