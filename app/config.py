from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_key: str = ""
    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4"

    class Config:
        env_file = ".env"