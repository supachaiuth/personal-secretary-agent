"""
Repository for persistent user memories.
"""
from supabase import Client
from app.services.supabase_service import get_supabase


class MemoryRepository:
    def __init__(self, client: Client = None):
        self.client = client or get_supabase()
    
    def get_by_user_id(self, user_id: str):
        return self.client.table("user_memories").select("*").eq("user_id", user_id).execute()
    
    def get_by_topic(self, user_id: str, topic: str):
        return self.client.table("user_memories").select("*").eq("user_id", user_id).eq("topic", topic).execute()
    
    def create(self, user_id: str, topic: str, content: str):
        return self.client.table("user_memories").insert({
            "user_id": user_id,
            "topic": topic,
            "content": content
        }).execute()
    
    def upsert_by_topic(self, user_id: str, topic: str, content: str):
        existing = self.get_by_topic(user_id, topic)
        if existing.data:
            return self.client.table("user_memories").update({
                "content": content,
                "updated_at": "now()"
            }).eq("user_id", user_id).eq("topic", topic).execute()
        else:
            return self.create(user_id, topic, content)
    
    def delete(self, memory_id: str):
        return self.client.table("user_memories").delete().eq("id", memory_id).execute()
