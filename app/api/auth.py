import os
import json
import logging
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import RedirectResponse, JSONResponse
from google_auth_oauthlib.flow import Flow
from app.repositories.user_repository import UserRepository
from app.services.supabase_service import get_supabase

logger = logging.getLogger(__name__)
router = APIRouter()
user_repo = UserRepository()

# Google OAuth2 scopes for calendar access
SCOPES = [
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/calendar.readonly'
]

# Redirect URI - must match what is registered in Google Cloud Console
# For local dev: http://localhost:8000/auth/google/callback
# For production: https://your-domain.com/auth/google/callback
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")

@router.get("/google/login")
async def google_login(line_user_id: str):
    """
    Initiate the Google OAuth2 flow.
    We pass line_user_id in the 'state' parameter to map the Google account to the LINE user later.
    """
    client_config = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI]
        }
    }
    
    if not client_config["web"]["client_id"] or not client_config["web"]["client_secret"]:
        raise HTTPException(status_code=500, detail="Google OAuth credentials not configured in .env")

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        state=line_user_id
    )
    flow.redirect_uri = REDIRECT_URI
    
    authorization_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent' # Force consent to ensure we always get a refresh_token
    )
    
    return RedirectResponse(authorization_url)

@router.get("/google/callback")
async def google_callback(
    request: Request,
    state: str = Query(...), # This is our line_user_id
    code: str = Query(...)
):
    """
    Callback from Google OAuth2.
    """
    client_config = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI]
        }
    }
    
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        state=state
    )
    flow.redirect_uri = REDIRECT_URI
    
    try:
        # Exchange auth code for tokens
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        refresh_token = credentials.refresh_token
        
        if not refresh_token:
            # If no refresh token, it might be because the user already authorized
            # and we didn't force consent. But we did prompt='consent'.
            logger.warning(f"No refresh token returned for user {state}. Prompting re-auth might be needed.")
            # Still, we can proceed if we have access token, but refresh is better for long-term.
        
        # Save refresh token to Supabase users table
        supabase = get_supabase()
        update_data = {
            "google_refresh_token": refresh_token,
            "calendar_sync_enabled": True
        }
        
        # We need to find the user row. UserRepository usually has get_by_line_user_id.
        result = supabase.table("users").update(update_data).eq("line_user_id", state).execute()
        
        if len(result.data) == 0:
            logger.error(f"Failed to find user with line_user_id {state} to save token.")
            return JSONResponse(
                status_code=404,
                content={"message": "ไม่พบข้อมูลผู้ใช้ในระบบ กรุณาลองใหม่อีกครั้ง"}
            )
            
        return JSONResponse(content={
            "message": "เชื่อมต่อ Google Calendar สำเร็จ! คุณสามารถปิดหน้านี้และกลับไปใช้งานใน LINE ได้เลยครับ",
            "status": "success"
        })
        
    except Exception as e:
        logger.error(f"Error in google_callback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
