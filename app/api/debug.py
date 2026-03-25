from fastapi import APIRouter
from app.services.scheduler_service import scheduler

router = APIRouter()

@router.post("/debug/reset-scheduler")
def reset_scheduler():
    """Reset scheduler daily state - for testing only"""
    scheduler.reset_daily_state()
    return {"message": "Scheduler state reset"}