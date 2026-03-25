from supabase import Client
from app.services.supabase_service import get_supabase


class UserRepository:
    def __init__(self, client: Client = None):
        self.client = client or get_supabase()

    def get_by_line_user_id(self, line_user_id: str):
        return self.client.table("users").select("*").eq("line_user_id", line_user_id).execute()

    def create(self, line_user_id: str, display_name: str = None, role: str = "partner"):
        return self.client.table("users").insert({
            "line_user_id": line_user_id,
            "display_name": display_name,
            "role": role
        }).execute()

    def get_all(self):
        return self.client.table("users").select("*").execute()
