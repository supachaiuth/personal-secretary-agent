from supabase import Client
from app.services.supabase_service import get_supabase


class PantryRepository:
    def __init__(self, client: Client = None):
        self.client = client or get_supabase()

    def get_by_user_id(self, user_id: str):
        return self.client.table("pantry_items").select("*").eq("user_id", user_id).execute()

    def create(self, user_id: str, item_name: str, quantity: int = 1, estimated_expiry_at: str = None):
        return self.client.table("pantry_items").insert({
            "user_id": user_id,
            "item_name": item_name,
            "quantity": quantity,
            "estimated_expiry_at": estimated_expiry_at
        }).execute()

    def update_quantity(self, item_id: str, quantity: int):
        return self.client.table("pantry_items").update({"quantity": quantity}).eq("id", item_id).execute()

    def delete(self, item_id: str):
        return self.client.table("pantry_items").delete().eq("id", item_id).execute()

    def get_expiring_soon(self, user_id: str, days: int = 3):
        return self.client.table("pantry_items").select("*").eq("user_id", user_id).lte("estimated_expiry_at", f"now() + '{days} days'::interval").execute()
