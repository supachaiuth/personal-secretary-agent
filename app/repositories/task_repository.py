from supabase import Client
from app.services.supabase_service import get_supabase


class TaskRepository:
    def __init__(self, client: Client = None):
        self.client = client or get_supabase()

    def get_by_user_id(self, user_id: str):
        return self.client.table("tasks").select("*").eq("user_id", user_id).execute()

    def create(self, user_id: str, title: str, due_date: str = None):
        return self.client.table("tasks").insert({
            "user_id": user_id,
            "title": title,
            "due_date": due_date,
            "status": "pending"
        }).execute()

    def update_status(self, task_id: str, status: str):
        return self.client.table("tasks").update({"status": status}).eq("id", task_id).execute()

    def delete(self, task_id: str):
        return self.client.table("tasks").delete().eq("id", task_id).execute()
