from supabase import create_client, Client
from app.config import Settings

_settings = Settings()


def get_supabase_client() -> Client:
    if not _settings.supabase_url or not _settings.supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(_settings.supabase_url, _settings.supabase_key)


def get_supabase() -> Client:
    return get_supabase_client()
