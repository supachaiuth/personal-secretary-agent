from supabase import Client
from app.services.supabase_service import get_supabase
import logging
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def normalize_reminder_message(message: str) -> str:
    """Normalize reminder message for comparison."""
    if not message:
        return ""
    normalized = message.lower().strip()
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized


class ReminderRepository:
    def __init__(self, client: Client = None):
        self.client = client or get_supabase()
    
    def get_by_user_id(self, user_id: str):
        return self.client.table("reminders").select("*").eq("user_id", user_id).execute()
    
    def get_pending(self, user_id: str):
        return self.client.table("reminders").select("*").eq("user_id", user_id).eq("sent", False).execute()
    
    def get_due_reminders(self):
        from datetime import datetime
        return self.client.table("reminders").select("*").eq("sent", False).lte("remind_at", datetime.now().isoformat()).execute()
    
    def find_duplicate(self, user_id: str, message: str, remind_at: str, max_diff_minutes: int = 5) -> dict:
        """
        Check if equivalent active reminder already exists.
        Returns existing reminder dict if duplicate found, None otherwise.
        """
        normalized_msg = normalize_reminder_message(message)
        
        result = self.client.table("reminders").select("*").eq("user_id", user_id).eq("sent", False).execute()
        
        for r in (result.data or []):
            existing_msg = r.get("message", "")
            existing_at = r.get("remind_at", "")
            
            if not existing_msg or not existing_at:
                continue
            
            existing_normalized = normalize_reminder_message(existing_msg)
            
            if existing_normalized == normalized_msg:
                try:
                    existing_dt = datetime.fromisoformat(existing_at.replace("Z", "+00:00"))
                    new_dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
                    diff_minutes = abs((existing_dt - new_dt).total_seconds() / 60)
                    
                    if diff_minutes <= max_diff_minutes:
                        logger.info(f"[ReminderRepo] Duplicate found: id={r.get('id')}, message={existing_msg}, diff_minutes={diff_minutes}")
                        return r
                except Exception as e:
                    logger.warning(f"[ReminderRepo] Date parse error: {e}")
        
        return None
    
    def create(self, user_id: str, message: str, remind_at: str):
        return self.client.table("reminders").insert({
            "user_id": user_id,
            "message": message,
            "remind_at": remind_at,
            "sent": False
        }).execute()
    
    def update(self, reminder_id: str, **updates):
        return self.client.table("reminders").update(updates).eq("id", reminder_id).execute()
    
    def mark_sent(self, reminder_id: str):
        return self.client.table("reminders").update({"sent": True}).eq("id", reminder_id).execute()
    
    def delete(self, reminder_id: str):
        return self.client.table("reminders").delete().eq("id", reminder_id).execute()
