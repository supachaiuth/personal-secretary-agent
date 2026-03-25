"""
Repository for activity logging (for daily summary).
"""
from supabase import Client
from app.services.supabase_service import get_supabase


class ActivityRepository:
    def __init__(self, client: Client = None):
        self.client = client or get_supabase()
    
    def log_activity(self, user_id: str, activity_type: str, activity_data: dict = None):
        return self.client.table("activity_logs").insert({
            "user_id": user_id,
            "activity_type": activity_type,
            "activity_data": activity_data
        }).execute()
    
    def get_today_activities(self, user_id: str):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        bkk = ZoneInfo("Asia/Bangkok")
        today_start = datetime.now(bkk).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.client.table("activity_logs").select("*").eq("user_id", user_id).gte("created_at", today_start.isoformat()).execute()
