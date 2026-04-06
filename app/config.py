from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_key: str = ""
    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    class Config:
        env_file = ".env"
        extra = "ignore"