import os
import logging
import httpx
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import icalendar
from app.services.supabase_service import get_supabase

logger = logging.getLogger(__name__)

class CalendarSyncService:
    def __init__(self):
        self.supabase = get_supabase()
        self.client_id = os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    def _get_google_service(self, refresh_token: str):
        """Get an authorized Google Calendar service using a refresh token."""
        creds = Credentials(
            None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=['https://www.googleapis.com/auth/calendar.events']
        )
        return build('calendar', 'v3', credentials=creds)

    async def sync_google_calendar(self, user_id: str, line_user_id: str):
        """Fetch events from Google Calendar and sync to Supabase."""
        try:
            # 1. Get user credentials
            user_res = self.supabase.table("users").select("google_refresh_token").eq("line_user_id", line_user_id).execute()
            if not user_res.data or not user_res.data[0].get("google_refresh_token"):
                return False
            
            refresh_token = user_res.data[0]["google_refresh_token"]
            service = self._get_google_service(refresh_token)
            
            # 2. Fetch events for the next 7 days
            now = datetime.utcnow().isoformat() + 'Z'
            max_time = (datetime.utcnow() + timedelta(days=7)).isoformat() + 'Z'
            
            events_result = service.events().list(
                calendarId='primary', 
                timeMin=now,
                timeMax=max_time,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # 3. Upsert into calendar_events table
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                
                event_data = {
                    "user_id": user_id,
                    "external_id": event['id'],
                    "source": "google",
                    "title": event.get('summary', 'No Title'),
                    "description": event.get('description', ''),
                    "location": event.get('location', ''),
                    "start_time": start,
                    "end_time": end,
                    "status": event.get('status', 'confirmed'),
                    "updated_at": datetime.utcnow().isoformat()
                }
                
                # Upsert query
                self.supabase.table("calendar_events").upsert(
                    event_data, 
                    on_conflict="external_id,source"
                ).execute()
                
            return True
        except Exception as e:
            logger.error(f"Error syncing Google Calendar for {user_id}: {e}")
            return False

    async def sync_apple_calendar(self, user_id: str, ical_url: str):
        """Fetch and parse Apple Calendar via iCal URL."""
        if not ical_url:
            return False
            
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(ical_url)
                if response.status_code != 200:
                    return False
            
            cal = icalendar.Calendar.from_ical(response.content)
            
            for component in cal.walk():
                if component.name == "VEVENT":
                    external_id = str(component.get('uid'))
                    start = component.get('dtstart').dt
                    end = component.get('dtend').dt if component.get('dtend') else None
                    
                    # Convert to ISO format
                    if isinstance(start, datetime):
                        start_iso = start.isoformat()
                    else: # date object
                        start_iso = start.isoformat() + "T00:00:00"
                        
                    event_data = {
                        "user_id": user_id,
                        "external_id": external_id,
                        "source": "apple",
                        "title": str(component.get('summary', 'No Title')),
                        "description": str(component.get('description', '')),
                        "location": str(component.get('location', '')),
                        "start_time": start_iso,
                        "status": "confirmed",
                        "updated_at": datetime.utcnow().isoformat()
                    }
                    
                    self.supabase.table("calendar_events").upsert(
                        event_data,
                        on_conflict="external_id,source"
                    ).execute()
            return True
        except Exception as e:
            logger.error(f"Error syncing Apple Calendar for {user_id}: {e}")
            return False

    async def create_google_event(self, line_user_id: str, title: str, start_time: str, end_time: Optional[str] = None):
        """Create a new event on Google Calendar."""
        try:
            user_res = self.supabase.table("users").select("*").eq("line_user_id", line_user_id).execute()
            if not user_res.data or not user_res.data[0].get("google_refresh_token"):
                return None
            
            refresh_token = user_res.data[0]["google_refresh_token"]
            service = self._get_google_service(refresh_token)
            
            if not end_time:
                # Default 1 hour duration
                st = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                et = st + timedelta(hours=1)
                end_time = et.isoformat()

            event = {
                'summary': title,
                'start': {'dateTime': start_time},
                'end': {'dateTime': end_time},
            }
            
            created_event = service.events().insert(calendarId='primary', body=event).execute()
            return created_event
        except Exception as e:
            logger.error(f"Error creating Google event for {line_user_id}: {e}")
            return None

calendar_sync_service = CalendarSyncService()
