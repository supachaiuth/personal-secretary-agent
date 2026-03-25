from supabase import Client
from app.services.supabase_service import get_supabase


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

    def create(self, user_id: str, message: str, remind_at: str):
        return self.client.table("reminders").insert({
            "user_id": user_id,
            "message": message,
            "remind_at": remind_at,
            "sent": False
        }).execute()

    def mark_sent(self, reminder_id: str):
        return self.client.table("reminders").update({"sent": True}).eq("id", reminder_id).execute()

    def delete(self, reminder_id: str):
        return self.client.table("reminders").delete().eq("id", reminder_id).execute()
