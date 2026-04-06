"""
Proactive Assistant Scheduler Service.

Implements:
- Morning Summary (configurable time, default 07:45)
- Advance Reminders (5 days, 2 days, same day before)
- Daily Summary (20:00)
- Smart Memory with deduplication
- Multi-user separated summaries
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta, time, date
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

from supabase import Client
from app.services.supabase_service import get_supabase
from app.services.line_service import push_message
from app.services.reminder_service import is_valid_reminder, INVALID_PREFIX

from app.services.calendar_sync_service import calendar_sync_service
logger = logging.getLogger(__name__)

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")

supabase: Client = get_supabase()


def filter_valid_reminders(reminders: List[Dict]) -> List[Dict]:
    """
    Filter out invalid reminders before including in summaries.
    
    Rules:
    - Must pass is_valid_reminder() check
    - Must not be marked with INVALID_PREFIX
    
    Returns:
        List of valid reminders only
    """
    valid = []
    for r in reminders:
        if is_valid_reminder(r):
            valid.append(r)
        else:
            logger.warning(f"[Scheduler] Filtering invalid reminder: id={r.get('id')}, message='{r.get('message', '')[:30]}...'")
    return valid


def deduplicate_reminders(reminders: List[Dict]) -> List[Dict]:
    """Remove duplicate reminders based on message content."""
    seen = set()
    unique = []
    for r in reminders:
        msg = r.get("message", "").strip()
        if msg and msg not in seen:
            seen.add(msg)
            unique.append(r)
    return unique


def parse_time_safe(time_value: Any, default: str = "00:00") -> time:
    """
    Safely parse time from various formats.
    
    Supports:
    - "HH:MM" (e.g., "07:45")
    - "HH:MM:SS" (e.g., "07:45:00")
    - Python time object
    - None or empty
    
    Returns:
        time object or default time if parsing fails
    """
    if time_value is None:
        logger.warning(f"[Scheduler] Time is None, using default {default}")
        return datetime.strptime(default, "%H:%M").time()
    
    if isinstance(time_value, time):
        return time_value
    
    time_str = str(time_value).strip()
    
    for fmt in ["%H:%M:%S", "%H:%M"]:
        try:
            parsed = datetime.strptime(time_str, fmt).time()
            logger.debug(f"[Scheduler] Parsed time '{time_str}' -> {parsed}")
            return parsed
        except ValueError:
            continue
    
    logger.error(f"[Scheduler] Failed to parse time: '{time_value}', using default {default}")
    return datetime.strptime(default, "%H:%M").time()


class ProactiveScheduler:
    """
    Proactive scheduler for:
    - morning_summary_job
    - advance_reminder_job
    - daily_summary_job
    """
    
    def __init__(self):
        self.is_running = False
        self.check_interval = 60
        self._last_advance_run: Optional[date] = None
    
    def reset_daily_state(self):
        """Reset daily run state - useful for testing"""
        self._last_advance_run = None
        logger.info("[SCHEDULER] Advance state reset for testing")
    
    def _format_summary_item(self, text: str, time_value: Any, item_type: str = "task") -> str:
        """
        Format a task/reminder item with optional time prefix.
        
        Rules:
        - If time exists → format as "HH:MM - <text>"
        - If no time → return text only
        - Strip any filler text from text
        - Backward-compatible: strip duplicated leading time if present
        
        Args:
            text: The item text (task title or reminder message)
            time_value: Time string or datetime (ISO format) or None
            item_type: "task" or "reminder"
        
        Returns:
            Formatted string with time prefix if available
        """
        import re
        
        logger.info(f"[OutputV2] raw_item={text[:50]}, type={item_type}")
        
        cleaned_text = text.strip()
        
        filler_patterns = [
            "รับทราบครับ", "รับทราบค่ะ", "ขอรายงาน", "นี่คือรายการ",
            "เตือน", "ช่วยเตือน", "แจ้งเตือน", "จำไว้นะ"
        ]
        for filler in filler_patterns:
            if cleaned_text.lower() == filler.lower():
                logger.warning(f"[OutputV2] stripped_filler={filler}")
                cleaned_text = ""
                break
        
        if not cleaned_text:
            logger.warning(f"[OutputV2] empty_after_cleaning")
            return ""
        
        if not time_value:
            logger.info(f"[OutputV2] normalized_text={cleaned_text[:30]}, time_prefix=none")
            return cleaned_text
        
        try:
            if isinstance(time_value, str):
                if "T" in time_value:
                    dt = datetime.fromisoformat(time_value.replace("Z", "+00:00")).astimezone(BANGKOK_TZ)
                    time_str = dt.strftime("%H:%M")
                else:
                    time_str = time_value.split(":")[0:2]
                    time_str = ":".join(time_str)
            elif isinstance(time_value, datetime):
                dt = time_value.astimezone(BANGKOK_TZ)
                time_str = dt.strftime("%H:%M")
            else:
                time_str = None
            
            if time_str:
                cleaned_text = self._strip_leading_time_dedup(cleaned_text, time_str)
                result = f"{time_str} - {cleaned_text}"
                logger.info(f"[OutputV2] normalized_text={cleaned_text[:30]}, time_prefix={time_str}, final_render={result[:50]}")
                return result
        except Exception as e:
            logger.warning(f"[OutputV2] time_parse_error={e}")
        
        logger.info(f"[OutputV2] normalized_text={cleaned_text[:30]}, time_prefix=none")
        return cleaned_text
    
    def _strip_leading_time_dedup(self, message: str, time_prefix: str) -> str:
        """
        Backward-compatible safeguard: strip duplicated leading time.
        
        If message starts with same time as time_prefix, strip it.
        E.g., time_prefix="09:00", message="09:00 ซักผ้า" -> "ซักผ้า"
        
        Also handles cases like "08:00-ล้างรถ" -> "ล้างรถ"
        """
        if not message or not time_prefix:
            return message
        
        message_stripped = message.strip()
        
        if message_stripped.startswith(time_prefix):
            remaining = message_stripped[len(time_prefix):].strip()
            remaining = re.sub(r'^[\s\-:]+', '', remaining)
            if remaining:
                logger.info(f"[DedupSafeguard] stripped leading time {time_prefix}, remaining='{remaining}'")
                return remaining
        
        time_pattern = re.match(r'^\d{2}:\\d{2}[\s\-:]*', message_stripped)
        if time_pattern:
            remaining = message_stripped[time_pattern.end():].strip()
            remaining = re.sub(r'^[\s\-:]+', '', remaining)
            if remaining:
                logger.info(f"[DedupSafeguard] found different leading time, stripping it")
                return remaining
        
        message_stripped = re.sub(r'^[^\w\u0e00-\u0fff]+', '', message_stripped)
        
        return message_stripped if message_stripped else message
    
    async def start(self):
        """Start the scheduler."""
        self.is_running = True
        logger.info("Proactive scheduler started")
        
        while self.is_running:
            try:
                now_utc = datetime.utcnow()
                now_bkk = datetime.now(BANGKOK_TZ)
                today = now_bkk.date()
                
                logger.info(f"[SCHEDULER] raw_server_time={now_utc.isoformat()} UTC")
                logger.info(f"[SCHEDULER] bangkok_time={now_bkk.isoformat()} Asia/Bangkok")
                
                await self.check_and_run_morning_summary(now_bkk, today)
                await self.check_and_run_advance_reminders(now_bkk, today)
                await self.check_and_run_daily_summary(now_bkk, today)
                
                await self.check_due_reminders()
                await self.check_advance_1hour_reminders()
                await self.check_calendar_1hour_reminders()
                await self.check_and_run_calendar_sync()
            
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            
            await asyncio.sleep(self.check_interval)
    
    def stop(self):
        """Stop the scheduler."""
        self.is_running = False
        logger.info("Proactive scheduler stopped")
    
    async def check_and_run_morning_summary(self, now_bkk: datetime, today: date):
        """Run morning summary at configured time (default 07:45) - per-user."""
        current_time = now_bkk.time()
        target_time_default = datetime.strptime("07:45", "%H:%M").time()
        window_minutes = 2
        window_end_time = (datetime.combine(datetime.today(), target_time_default) + timedelta(minutes=window_minutes)).time()
        
        logger.info(f"[SCHEDULER] morning_summary CHECK: current={current_time} target={target_time_default} window_end={window_end_time}")
        
        users = self._get_users_with_morning_enabled()
        
        if not users:
            logger.info(f"[SCHEDULER] morning_summary SKIP: no_users_enabled")
            return
        
        for user in users:
            user_id = user.get("id")
            user_time = user.get("morning_summary_time") or "07:45"
            enabled = user.get("morning_summary_enabled")
            
            logger.info(f"[SCHEDULER] morning_summary USER: user_id={user_id} enabled={enabled} user_time={user_time}")
            
            if not enabled:
                logger.info(f"[SCHEDULER] morning_summary USER_SKIP: user_id={user_id} reason=not_enabled")
                continue
            
            target_time = parse_time_safe(user_time, "07:45")
            user_window_end = (datetime.combine(datetime.today(), target_time) + timedelta(minutes=window_minutes)).time()
            
            logger.info(f"[SCHEDULER] morning_summary USER: user_id={user_id} current={current_time} target={target_time} window_end={user_window_end}")
            
            if current_time < target_time:
                logger.info(f"[SCHEDULER] morning_summary USER_SKIP: user_id={user_id} reason=too_early")
                continue
            
            if current_time > user_window_end:
                logger.info(f"[SCHEDULER] morning_summary USER_SKIP: user_id={user_id} reason=missed_window")
                continue
            
            if self._user_has_summary_today(user_id, "morning", today):
                logger.info(f"[SCHEDULER] morning_summary USER_SKIP: user_id={user_id} reason=already_sent_today")
                continue
            
            logger.info(f"[SCHEDULER] morning_summary USER_EXECUTE: user_id={user_id} reason=within_window")
            try:
                success = await self._run_morning_summary_for_user(user)
                if success:
                    logger.info(f"[SCHEDULER] morning_summary SUCCESS: user_id={user_id}")
                else:
                    logger.warning(f"[SCHEDULER] morning_summary FAILED: user_id={user_id} push_failed")
            except Exception as e:
                logger.error(f"[SCHEDULER] morning_summary ERROR: user_id={user_id} error={e}")
    
    async def check_and_run_advance_reminders(self, now_bkk: datetime, today: date):
        """Run advance reminders check (5 days, 2 days, same day)."""
        if self._last_advance_run == today:
            return
        
        if now_bkk.hour == 6:
            try:
                await self._run_advance_reminders()
                logger.info("Advance reminders check completed")
            except Exception as e:
                logger.error(f"Error in advance reminders: {e}")
        
        self._last_advance_run = today
    
    async def check_and_run_daily_summary(self, now_bkk: datetime, today: date):
        """Run daily summary at configured time (default 20:00) - per-user."""
        current_time = now_bkk.time()
        target_time_default = datetime.strptime("20:00", "%H:%M").time()
        window_minutes = 2
        window_end_time = (datetime.combine(datetime.today(), target_time_default) + timedelta(minutes=window_minutes)).time()
        
        logger.info(f"[SCHEDULER] daily_summary CHECK: current={current_time} target={target_time_default} window_end={window_end_time}")
        
        users = self._get_users_with_daily_enabled()
        
        if not users:
            logger.info(f"[SCHEDULER] daily_summary SKIP: no_users_enabled")
            return
        
        for user in users:
            user_id = user.get("id")
            user_time = user.get("daily_summary_time") or "20:00"
            enabled = user.get("daily_summary_enabled")
            
            logger.info(f"[SCHEDULER] daily_summary USER: user_id={user_id} enabled={enabled} user_time={user_time}")
            
            if not enabled:
                logger.info(f"[SCHEDULER] daily_summary USER_SKIP: user_id={user_id} reason=not_enabled")
                continue
            
            target_time = parse_time_safe(user_time, "20:00")
            user_window_end = (datetime.combine(datetime.today(), target_time) + timedelta(minutes=window_minutes)).time()
            
            logger.info(f"[SCHEDULER] daily_summary USER: user_id={user_id} current={current_time} target={target_time} window_end={user_window_end}")
            
            if current_time < target_time:
                logger.info(f"[SCHEDULER] daily_summary USER_SKIP: user_id={user_id} reason=too_early")
                continue
            
            if current_time > user_window_end:
                logger.info(f"[SCHEDULER] daily_summary USER_SKIP: user_id={user_id} reason=missed_window")
                continue
            
            if self._user_has_summary_today(user_id, "daily", today):
                logger.info(f"[SCHEDULER] daily_summary USER_SKIP: user_id={user_id} reason=already_sent_today")
                continue
            
            logger.info(f"[SCHEDULER] daily_summary USER_EXECUTE: user_id={user_id} reason=within_window")
            try:
                success = await self._run_daily_summary_for_user(user)
                if success:
                    logger.info(f"[SCHEDULER] daily_summary SUCCESS: user_id={user_id}")
                else:
                    logger.warning(f"[SCHEDULER] daily_summary FAILED: user_id={user_id} push_failed")
            except Exception as e:
                logger.error(f"[SCHEDULER] daily_summary ERROR: user_id={user_id} error={e}")
    
    async def check_advance_1hour_reminders(self):
        """Check and send 1-hour advance reminders."""
        try:
            now_bkk = datetime.now(BANGKOK_TZ)
            window_start = now_bkk + timedelta(minutes=55)
            window_end = now_bkk + timedelta(minutes=65)
            
            result = supabase.table("reminders").select("*").eq("sent", False).execute()
            if not result.data:
                return
            
            # Filter reminders in the 1-hour window
            upcoming = []
            for r in result.data:
                remind_at_str = r.get("remind_at", "")
                if not remind_at_str:
                    continue
                try:
                    remind_dt = datetime.fromisoformat(remind_at_str.replace("Z", "+00:00")).astimezone(BANGKOK_TZ)
                    if window_start <= remind_dt <= window_end:
                        upcoming.append(r)
                except Exception:
                    pass
            
            if not upcoming:
                return
            
            # Check which ones already had 1h notice sent
            reminder_ids = [r.get("id") for r in upcoming if r.get("id")]
            sent_result = supabase.table("reminder_sent_logs").select("reminder_id").in_("reminder_id", reminder_ids).eq("sent_type", "1hour").execute()
            already_sent_ids = {s.get("reminder_id") for s in (sent_result.data or [])}
            
            for reminder in upcoming:
                reminder_id = reminder.get("id")
                if str(reminder_id) in already_sent_ids:
                    logger.info(f"[1hr Reminder] Already sent 1h notice for id={reminder_id}")
                    continue
                
                if not is_valid_reminder(reminder):
                    continue
                
                user_id = reminder.get("user_id")
                message = reminder.get("message", "")
                remind_at_str = reminder.get("remind_at", "")
                
                user_result = supabase.table("users").select("line_user_id").eq("id", user_id).execute()
                if not user_result.data:
                    continue
                
                line_user_id = user_result.data[0].get("line_user_id")
                if not line_user_id:
                    continue
                
                # Format reminder time
                try:
                    remind_dt = datetime.fromisoformat(remind_at_str.replace("Z", "+00:00")).astimezone(BANGKOK_TZ)
                    time_display = remind_dt.strftime("%H:%M")
                except Exception:
                    time_display = ""
                
                text = f"⏰ อีก 1 ชั่วโมง:\n\n{message}"
                if time_display:
                    text = f"⏰ แจ้งเตือนล่วงหน้า (1 ชั่วโมง)\nเวลา {time_display} น. — {message}"
                
                push_message(line_user_id, text)
                logger.info(f"[1hr Reminder] Sent 1h advance notice to {line_user_id}: {message}")
                
                # Log so we don't send again (but DO NOT mark sent=True, still need the on-time one)
                supabase.table("reminder_sent_logs").insert({
                    "reminder_id": str(reminder_id),
                    "sent_type": "1hour"
                }).execute()
        
        except Exception as e:
            logger.error(f"[1hr Reminder] Error: {e}")
    
    async def check_calendar_1hour_reminders(self):
        """Check for calendar events starting in exactly 1 hour and notify."""
        now_bkk = datetime.now(BANGKOK_TZ)
        target_time = now_bkk + timedelta(hours=1)
        
        # Look for events starting in the next 2 minutes of the target window
        start_range = target_time.replace(second=0, microsecond=0)
        end_range = start_range + timedelta(minutes=2)
        
        try:
            # Query calendar_events
            result = supabase.table("calendar_events") \
                .select("*, users!inner(line_user_id)") \
                .gte("start_time", start_range.isoformat()) \
                .lt("start_time", end_range.isoformat()) \
                .execute()
            
            for event in (result.data or []):
                event_id = event.get("id")
                line_user_id = event.get("users", {}).get("line_user_id")
                if line_user_id:
                    title = event.get("title", "นัดหมาย")
                    start_dt = datetime.fromisoformat(event.get("start_time").replace("Z", "+00:00")).astimezone(BANGKOK_TZ)
                    time_str = start_dt.strftime("%H:%M")
                    
                    msg = f"🔔 เตือนความจำ: อีก 1 ชั่วโมงคุณมีนัดหมาย\n\n🗓️ {title}\n⏰ เวลา {time_str} น."
                    push_message(line_user_id, msg)
                    logger.info(f"[SCHEDULER] Sent 1h calendar notification for event {event_id}")
                    
        except Exception as e:
            logger.error(f"[SCHEDULER] Error checking calendar 1h reminders: {e}")

    async def check_and_run_calendar_sync(self):
        """Periodically sync external calendars for all users."""
        if not hasattr(self, "_last_sync_time"):
            self._last_sync_time = datetime.min
            
        now = datetime.now()
        if (now - self._last_sync_time).total_seconds() < 1800: # 30 minutes
            return
            
        self._last_sync_time = now
        logger.info("[SCHEDULER] Starting periodic calendar sync")
        
        try:
            users_res = supabase.table("users").select("*").eq("calendar_sync_enabled", True).execute()
            for user in (users_res.data or []):
                user_id = user.get("id")
                line_user_id = user.get("line_user_id")
                
                if user.get("google_refresh_token"):
                    await calendar_sync_service.sync_google_calendar(user_id, line_user_id)
        except Exception as e:
            logger.error(f"[SCHEDULER] Error during periodic calendar sync: {e}")

    async def check_due_reminders(self):
        """Check and send due reminders."""
        try:
            result = supabase.table("reminders").select("*").eq("sent", False).lte("remind_at", datetime.now(BANGKOK_TZ).isoformat()).execute()
            
            if not result.data:
                return
            
            sent_today = set()
            sent_result = supabase.table("reminder_sent_logs").select("reminder_id").eq("sent_type", "due").execute()
            for sr in (sent_result.data or []):
                sent_today.add(sr.get("reminder_id"))
            
            for reminder in result.data:
                if not is_valid_reminder(reminder):
                    logger.warning(f"[Due Reminder] Skipping invalid reminder id={reminder.get('id')}")
                    continue
                
                reminder_id = reminder.get("id")
                
                if str(reminder_id) in sent_today:
                    logger.info(f"[Due Reminder] Skipping already sent reminder id={reminder_id}")
                    continue
                
                user_id = reminder.get("user_id")
                message = reminder.get("message")
                
                user_result = supabase.table("users").select("line_user_id, display_name").eq("id", user_id).execute()
                if not user_result.data:
                    continue
                
                line_user_id = user_result.data[0].get("line_user_id")
                display_name = user_result.data[0].get("display_name", "คุณ")
                
                if line_user_id:
                    import random
                    due_greetings = [
                        "ถึงเวลาแล้วครับ! ⏰",
                        "ได้เวลาแล้วคร้าบ 🔔",
                        "อย่าลืมนัดหมายนะจ้ะ 📌",
                        "เตือนความจำครับ ⏰",
                        "ถึงเวลานัดแล้วจ๊ะ! ✨",
                        "ได้เวลาตามที่นัดไว้แล้วครับ 🕒"
                    ]
                    greeting = random.choice(due_greetings)
                    text = f"{greeting}\n\n{message}"
                    push_message(line_user_id, text)
                    logger.info(f"Sent due reminder to {line_user_id}: {message}")
                
                supabase.table("reminders").update({"sent": True}).eq("id", reminder_id).execute()
                
                supabase.table("reminder_sent_logs").insert({
                    "reminder_id": reminder_id,
                    "sent_type": "due"
                }).execute()
        
        except Exception as e:
            logger.error(f"Error checking due reminders: {e}")
    
    def _get_users_with_morning_enabled(self) -> List[Dict]:
        """Get users with morning summary enabled."""
        result = supabase.table("users").select("*").eq("morning_summary_enabled", True).execute()
        return result.data or []
    
    def _get_users_with_daily_enabled(self) -> List[Dict]:
        """Get users with daily summary enabled."""
        result = supabase.table("users").select("*").eq("daily_summary_enabled", True).execute()
        return result.data or []
    
    def _user_has_summary_today(self, user_id: str, summary_type: str, today: date) -> bool:
        """Check if user already received this summary type today (Bangkok timezone)."""
        today_start = datetime.now(BANGKOK_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        today_iso = today_start.isoformat()
        
        logger.info(f"[SCHEDULER] DEBUG: summary_logs query using sent_at (NOT created_at) for user_id={user_id} type={summary_type}")
        result = supabase.table("summary_logs").select("id").eq("user_id", user_id).eq("summary_type", summary_type).gte("sent_at", today_iso).execute()
        
        has_log = len(result.data or []) > 0
        logger.info(f"[SCHEDULER] summary_logs CHECK: user_id={user_id} type={summary_type} today={today_iso} found={has_log} count={len(result.data or [])}")
        
        return has_log
    
    async def _run_morning_summary_for_user(self, user: Dict):
        """Generate and send morning summary for a user."""
        user_id = user.get("id")
        line_user_id = user.get("line_user_id")
        display_name = user.get("display_name", "คุณ")
        
        if not line_user_id:
            return
        
        today_start = datetime.now(BANGKOK_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        tasks_result = supabase.table("tasks").select("*").eq("user_id", user_id).in_("status", ["pending", "in_progress"]).order("created_at", desc=True).execute()
        pending_tasks = [t for t in (tasks_result.data or []) if t.get("due_date") and t.get("due_date")[:10] == today_start.strftime("%Y-%m-%d")]
        
        reminders_result = supabase.table("reminders").select("*").eq("user_id", user_id).eq("sent", False).execute()
        today_reminders = []
        for r in (reminders_result.data or []):
            remind_at = r.get("remind_at")
            if remind_at:
                remind_dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
                if remind_dt.date() == today_start.date():
                    today_reminders.append(r)
        
        today_reminders = deduplicate_reminders(filter_valid_reminders(today_reminders))
        logger.info(f"[Morning Summary] Valid reminders for user {user_id}: {len(today_reminders)}")
        
        memories = self._get_smart_memories(user_id)
        
        parking_mem = self.get_latest_parking_memory(user_id)
        
        message = self._format_morning_summary(display_name, pending_tasks, today_reminders, memories, parking_mem)
        
        if push_message(line_user_id, message):
            supabase.table("summary_logs").insert({
                "user_id": user_id,
                "summary_type": "morning",
                "sent_at": datetime.now(BANGKOK_TZ).isoformat(),
                "content_summary": f"tasks:{len(pending_tasks)}, reminders:{len(today_reminders)}"
            }).execute()
            logger.info(f"[SCHEDULER] morning_summary logged to DB: user_id={user_id}")
            return True
        else:
            logger.warning(f"[SCHEDULER] morning_summary push_failed: user_id={user_id}")
            return False
    
    async def _run_daily_summary_for_user(self, user: Dict):
        """Generate and send daily summary for a user."""
        user_id = user.get("id")
        line_user_id = user.get("line_user_id")
        display_name = user.get("display_name", "คุณ")
        
        if not line_user_id:
            return
        
        today_start = datetime.now(BANGKOK_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        
        activities_result = supabase.table("activity_logs").select("*").eq("user_id", user_id).gte("created_at", today_start.isoformat()).execute()
        activities = activities_result.data or []
        
        tasks_created_list = [a for a in activities if a.get("activity_type") == "task_created"]
        reminders_created_list = [a for a in activities if a.get("activity_type") == "reminder_created"]
        pantry_updates_list = [a for a in activities if a.get("activity_type") == "pantry_updated"]
        
        tasks_created = len(tasks_created_list)
        reminders_created = len(reminders_created_list)
        pantry_updates = len(pantry_updates_list)
        
        task_items = []
        for a in tasks_created_list:
            details = a.get("activity_data", {})
            if isinstance(details, dict):
                title = details.get("title", "")
                due_time = details.get("due_time") or details.get("due_date", "")
                logger.info(f"[Daily Summary] raw item: {title}")
                if title and len(title.strip()) > 0:
                    formatted_item = self._format_summary_item(title, due_time, "task")
                    task_items.append(formatted_item)
                    logger.info(f"[Daily Summary] extracted item text: {title}")
                else:
                    logger.warning(f"[Daily Summary] skipped empty item: {details}")
            else:
                logger.warning(f"[Daily Summary] skipped empty item: not dict - {details}")
        
        reminder_items = []
        for a in reminders_created_list:
            details = a.get("activity_data", {})
            if isinstance(details, dict):
                msg = details.get("message", "")
                remind_at = details.get("remind_at", "")
                logger.info(f"[Daily Summary] raw item: {msg}")
                if msg and len(msg.strip()) > 0:
                    formatted_item = self._format_summary_item(msg, remind_at, "reminder")
                    reminder_items.append(formatted_item)
                    logger.info(f"[Daily Summary] extracted item text: {msg}")
                else:
                    logger.warning(f"[Daily Summary] skipped empty item: {details}")
            else:
                logger.warning(f"[Daily Summary] skipped empty item: not dict - {details}")
        
        pantry_items = []
        for a in pantry_updates_list:
            details = a.get("activity_data", {})
            if isinstance(details, dict):
                action = details.get("action", "")
                item = details.get("item_name", "")
                logger.info(f"[Daily Summary] raw pantry item: action={action}, item={item}")
                if action == "add" and item:
                    pantry_items.append(f"เพิ่ม {item}")
                    logger.info(f"[Daily Summary] extracted item text: เพิ่ม {item}")
                elif action == "remove" and item:
                    pantry_items.append(f"ลบ {item}")
                    logger.info(f"[Daily Summary] extracted item text: ลบ {item}")
                elif item:
                    pantry_items.append(item)
                    logger.info(f"[Daily Summary] extracted item text: {item}")
                else:
                    logger.warning(f"[Daily Summary] skipped empty item: {details}")
            else:
                logger.warning(f"[Daily Summary] skipped empty item: not dict - {details}")
        
        logger.info(f"[Daily Summary] Today items: tasks={tasks_created}, reminders={reminders_created}, pantry={pantry_updates}")
        
        upcoming_result = supabase.table("reminders").select("*").eq("user_id", user_id).eq("sent", False).gte("remind_at", datetime.now(BANGKOK_TZ).isoformat()).order("remind_at", desc=False).execute()
        upcoming = upcoming_result.data or []
        
        fetched_count = len(upcoming)
        logger.info(f"[UpcomingSort] fetched_count={fetched_count}")
        
        upcoming = filter_valid_reminders(upcoming)
        after_filter_count = len(upcoming)
        logger.info(f"[UpcomingSort] after_filter_count={after_filter_count}")
        
        upcoming = deduplicate_reminders(upcoming)
        after_dedup_count = len(upcoming)
        logger.info(f"[UpcomingSort] after_dedup_count={after_dedup_count}")
        
        try:
            upcoming = sorted(upcoming, key=lambda x: datetime.fromisoformat(x.get("remind_at", "").replace("Z", "+00:00")).astimezone(BANGKOK_TZ))
            logger.info(f"[UpcomingSort] sorted=True first_items_after_sort={[u.get('remind_at', '')[:16] for u in upcoming[:3]]}")
        except Exception as e:
            logger.warning(f"[UpcomingSort] sort_error={e}")
        
        logger.info(f"[Daily Summary] Valid upcoming reminders for user {user_id}: {len(upcoming)}")
        
        today_parking = self.get_latest_parking_memory(user_id)
        
        message = self._format_daily_summary(display_name, tasks_created, reminders_created, pantry_updates, upcoming, today_parking, task_items, reminder_items, pantry_items)
        
        if push_message(line_user_id, message):
            supabase.table("summary_logs").insert({
                "user_id": user_id,
                "summary_type": "daily",
                "sent_at": datetime.now(BANGKOK_TZ).isoformat(),
                "content_summary": f"tasks:{tasks_created}, reminders:{reminders_created}, pantry:{pantry_updates}"
            }).execute()
            logger.info(f"[SCHEDULER] daily_summary logged to DB: user_id={user_id}")
            return True
        else:
            logger.warning(f"[SCHEDULER] daily_summary push_failed: user_id={user_id}")
            return False
    
    async def _run_advance_reminders(self):
        """Check and send advance reminders for 5 days, 2 days, same day."""
        now = datetime.now(BANGKOK_TZ)
        
        await self._check_advance_reminder_type("5day", 5, now)
        await self._check_advance_reminder_type("2day", 2, now)
        await self._check_advance_reminder_type("same_day", 0, now)
    
    async def _check_advance_reminder_type(self, sent_type: str, days_before: int, now: datetime):
        """Check for reminders expiring in specific days."""
        target_date = (now + timedelta(days=days_before)).date()
        
        users = self._get_users_with_advance_enabled()
        
        for user in users:
            user_id = user.get("id")
            line_user_id = user.get("line_user_id")
            
            if not line_user_id:
                continue
            
            start_of_target = datetime.combine(target_date, time.min, tzinfo=BANGKOK_TZ)
            end_of_target = datetime.combine(target_date, time.max, tzinfo=BANGKOK_TZ)
            
            reminders_result = supabase.table("reminders").select("*").eq("user_id", user_id).eq("sent", False).execute()
            target_reminders = []
            for r in (reminders_result.data or []):
                remind_at = r.get("remind_at")
                if remind_at:
                    remind_dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00")).astimezone(BANGKOK_TZ)
                    if start_of_target <= remind_dt <= end_of_target:
                        target_reminders.append(r)
            
            target_reminders = deduplicate_reminders(filter_valid_reminders(target_reminders))
            logger.info(f"[Advance {sent_type}] Valid reminders for user {user_id}: {len(target_reminders)}")
            
            if days_before == 0:
                pantry_result = supabase.table("pantry_items").select("*").eq("user_id", user_id).execute()
                expiring_pantry = []
                for p in (pantry_result.data or []):
                    expiry = p.get("estimated_expiry_at")
                    if expiry:
                        expiry_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00")).astimezone(BANGKOK_TZ)
                        if expiry_dt.date() == target_date:
                            expiring_pantry.append(p)
            else:
                expiring_pantry = []
            
            already_sent = self._check_already_sent(user_id, target_reminders, sent_type)
            target_reminders = [r for r in target_reminders if r.get("id") not in already_sent]
            
            if not target_reminders and not expiring_pantry:
                continue
            
            message = self._format_advance_reminder(target_reminders, expiring_pantry, days_before)
            
            if push_message(line_user_id, message):
                for r in target_reminders:
                    supabase.table("reminder_sent_logs").insert({
                        "reminder_id": r.get("id"),
                        "sent_type": sent_type
                    }).execute()
    
    def _get_users_with_advance_enabled(self) -> List[Dict]:
        """Get users with advance reminder enabled."""
        result = supabase.table("users").select("*").eq("advance_reminder_enabled", True).execute()
        return result.data or []
    
    def _check_already_sent(self, user_id: str, reminders: List[Dict], sent_type: str) -> set:
        """Check which reminders have already been sent."""
        reminder_ids = [r.get("id") for r in reminders if r.get("id")]
        if not reminder_ids:
            return set()
        
        result = supabase.table("reminder_sent_logs").select("reminder_id").in_("reminder_id", reminder_ids).eq("sent_type", sent_type).execute()
        return {r.get("reminder_id") for r in (result.data or [])}
    
    def _get_smart_memories(self, user_id: str) -> List[Dict]:
        """Get latest memory per topic (deduplicated)."""
        result = supabase.table("user_memories").select("*").eq("user_id", user_id).order("updated_at", desc=True).execute()
        
        if not result.data:
            return []
        
        topics_seen = {}
        for mem in result.data:
            topic = mem.get("topic")
            if topic not in topics_seen:
                topics_seen[topic] = mem
        
        return list(topics_seen.values())
    
    def get_latest_parking_memory(self, user_id: str) -> Optional[Dict]:
        """Get latest parking memory for a user."""
        result = supabase.table("user_memories").select("*").eq("user_id", user_id).eq("topic", "parking").order("updated_at", desc=True).limit(1).execute()
        
        if result.data and len(result.data) > 0:
            mem = result.data[0]
            logger.info(f"[SUMMARY] parking_memory_found user_id={user_id} location={mem.get('content')}")
            return mem
        
        logger.info(f"[SUMMARY] parking_memory_skipped user_id={user_id} reason=no_data")
        return None
    
    def get_latest_parking_memory(self, user_id: str) -> Optional[Dict]:
        """Get latest parking memory for a user (regardless of when updated)."""
        result = supabase.table("user_memories").select("*").eq("user_id", user_id).eq("topic", "parking").order("updated_at", desc=True).limit(1).execute()
        
        if result.data and len(result.data) > 0:
            mem = result.data[0]
            logger.info(f"[SUMMARY] parking_memory_found user_id={user_id} location={mem.get('content')} updated_at={mem.get('updated_at')}")
            return mem
        
        logger.info(f"[SUMMARY] parking_memory_not_found user_id={user_id} reason=no_data")
        return None
    
    def get_today_parking_memory(self, user_id: str) -> Optional[Dict]:
        """Get today's parking memory for a user (updated today in Bangkok time)."""
        today_start = datetime.now(BANGKOK_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        
        result = supabase.table("user_memories").select("*").eq("user_id", user_id).eq("topic", "parking").gte("updated_at", today_start.isoformat()).order("updated_at", desc=True).limit(1).execute()
        
        if result.data and len(result.data) > 0:
            mem = result.data[0]
            logger.info(f"[SUMMARY] parking_memory_found user_id={user_id} location={mem.get('content')} type=today")
            return mem
        
        logger.info(f"[SUMMARY] parking_memory_skipped user_id={user_id} reason=no_data_today")
        return None
    
    def _format_morning_summary(self, display_name: str, tasks: List[Dict], reminders: List[Dict], memories: List[Dict], parking_mem: Optional[Dict] = None) -> str:
        """Format morning summary message."""
        from app.services.reminder_service import reminder_service
        
        lines = ["🌅 สรุปเช้านี้", ""]
        
        lines.append("📋 วันนี้:")
        
        if tasks:
            task_list = "\n".join([f"  • {t.get('title', '')}" for t in tasks[:5]])
            lines.append(f"  งาน:\n{task_list}")
        else:
            lines.append("  ไม่มีงานที่ต้องทำ")
        
        if reminders:
            rendered_reminders = []
            for r in reminders[:3]:
                formatted = reminder_service.format_reminder_display(r)
                if formatted:
                    rendered_reminders.append(formatted)
            
            if rendered_reminders:
                rem_list = "\n".join([f"  • {item}" for item in rendered_reminders])
                lines.append(f"  เตือน:\n{rem_list}")
            else:
                lines.append("  ไม่มีเตือน")
        
        if memories:
            lines.append("")
            lines.append("🧠 จดจำ:")
            for mem in memories[:3]:
                content = mem.get("content", "")
                updated = mem.get("updated_at")
                if updated:
                    diff = self._get_time_diff(updated)
                    lines.append(f"  • {content} ({diff})")
                else:
                    lines.append(f"  • {content}")
        
        if parking_mem:
            parking_message = self._format_parking_message(parking_mem)
            if parking_message:
                lines.append("")
                lines.append("🚗 สิ่งที่ควรจำ:")
                lines.append(f"  • {parking_message}")
        
        lines.append("")
        lines.append("สวัสดีครับ ☀️")
        
        return "\n".join(lines)
    
    def _format_advance_reminder(self, reminders: List[Dict], pantry: List[Dict], days_before: int) -> str:
        """Format advance reminder message."""
        lines = []
        
        if days_before == 0:
            lines.append("📅 วันนี้:")
        elif days_before == 1:
            lines.append("📅 พรุ่งนี้:")
        else:
            lines.append(f"📅 อีก {days_before} วัน:")
        
        has_items = False
        
        if reminders:
            has_items = True
            lines.append("  เตือน:")
            for r in reminders:
                lines.append(f"  • {r.get('message', '')}")
        
        if pantry:
            has_items = True
            lines.append("  ของหมดอายุ:")
            for p in pantry:
                lines.append(f"  • {p.get('item_name', '')} ({p.get('quantity', 1)})")
        
        if not has_items:
            lines.append("  ไม่มีรายการที่ต้องเตือน")
        
        return "\n".join(lines)
    
    def _format_daily_summary(
        self,
        display_name: str,
        tasks_created: int,
        reminders_created: int,
        pantry_updates: int,
        upcoming: List[Dict],
        today_parking: Optional[Dict] = None,
        task_items: List[str] = None,
        reminder_items: List[str] = None,
        pantry_items: List[str] = None
    ) -> str:
        """Format daily summary message with itemized breakdown."""
        MAX_ITEMS = 3
        
        lines = ["🌙 สรุปประจำวัน", ""]
        
        lines.append("📊 วันนี้:")
        
        if tasks_created > 0:
            lines.append(f"  • งานใหม่: {tasks_created}")
            valid_tasks = [item for item in task_items if item and len(item.strip()) > 0]
            if valid_tasks:
                for item in valid_tasks[:MAX_ITEMS]:
                    lines.append(f"    - {item}")
                if len(valid_tasks) > MAX_ITEMS:
                    lines.append(f"    (และอีก {len(valid_tasks) - MAX_ITEMS} รายการ)")
            rendered = min(len(valid_tasks), MAX_ITEMS) if valid_tasks else 0
            logger.info(f"[Daily Summary] rendered items: {rendered}/{len(valid_tasks)} (valid/total)")
        else:
            lines.append("  • งานใหม่: 0")
        
        if reminders_created > 0:
            lines.append(f"  • เตือนใหม่: {reminders_created}")
            valid_reminders = [item for item in reminder_items if item and len(item.strip()) > 0]
            if valid_reminders:
                for item in valid_reminders[:MAX_ITEMS]:
                    lines.append(f"    - {item}")
                if len(valid_reminders) > MAX_ITEMS:
                    lines.append(f"    (และอีก {len(valid_reminders) - MAX_ITEMS} รายการ)")
            rendered = min(len(valid_reminders), MAX_ITEMS) if valid_reminders else 0
            logger.info(f"[Daily Summary] rendered items: {rendered}/{len(valid_reminders)} (valid/total)")
        else:
            lines.append("  • เตือนใหม่: 0")
        
        if pantry_updates > 0:
            lines.append(f"  • อัปเดตตู้เย็น: {pantry_updates}")
            valid_pantry = [item for item in pantry_items if item and len(item.strip()) > 0]
            if valid_pantry:
                for item in valid_pantry[:MAX_ITEMS]:
                    lines.append(f"    - {item}")
                if len(valid_pantry) > MAX_ITEMS:
                    lines.append(f"    (และอีก {len(valid_pantry) - MAX_ITEMS} รายการ)")
            rendered = min(len(valid_pantry), MAX_ITEMS) if valid_pantry else 0
            logger.info(f"[Daily Summary] rendered items: {rendered}/{len(valid_pantry)} (valid/total)")
        else:
            lines.append("  • อัปเดตตู้เย็น: 0")
        
        if upcoming:
            lines.append("")
            lines.append("📅 วันข้างหน้า:")
            for u in upcoming[:5]:
                remind_at = u.get("remind_at", "")
                if remind_at:
                    dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00")).astimezone(BANGKOK_TZ)
                    date_str = dt.strftime("%d/%m %H:%M")
                    lines.append(f"  • {date_str} - {u.get('message', '')}")
        
        parking_message = self._format_parking_message(today_parking)
        if parking_message:
            lines.append("")
            lines.append("🚗 อัปเดตที่ควรจำ:")
            lines.append(f"  • {parking_message}")
        
        logger.info(f"[OutputV2] final_render=summary_without_filler")
        
        return "\n".join(lines)
    
    def _format_parking_message(self, parking_data: Optional[Dict]) -> Optional[str]:
        """
        Format parking message based on freshness.
        
        Rules:
        - days_diff >= 4: DO NOT show (return None)
        - days_diff <= 1: "คุณจอดรถไว้ที่ ชั้น {location}"
        - days_diff == 2 or 3: "จอดรถที่ชั้น {location} (เมื่อ {days_diff} วันที่แล้ว)"
        - no data: return None
        """
        if not parking_data:
            logger.info(f"[ParkingSummary] show_parking=False reason=no_parking_data")
            return None
        
        content = parking_data.get("content", "")
        updated_at = parking_data.get("updated_at", "")
        
        if not content or not updated_at:
            logger.info(f"[ParkingSummary] show_parking=False reason=empty_data")
            return None
        
        try:
            updated_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).astimezone(BANGKOK_TZ)
            current_date = datetime.now(BANGKOK_TZ).date()
            parking_date = updated_dt.date()
            days_diff = (current_date - parking_date).days
            
            logger.info(f"[ParkingSummary] parking_updated_at={updated_at}")
            logger.info(f"[ParkingSummary] current_date={current_date.isoformat()}")
            logger.info(f"[ParkingSummary] days_diff={days_diff}")
            
            if days_diff >= 4:
                logger.info(f"[ParkingSummary] show_parking=False reason=days_diff>=4")
                return None
            
            location = content.strip()
            
            if days_diff <= 1:
                message = f"คุณจอดรถไว้ที่ {location}"
                logger.info(f"[ParkingSummary] show_parking=True format=normal")
                return message
            elif days_diff == 2 or days_diff == 3:
                message = f"จอดรถที่{location} (เมื่อ {days_diff} วันที่แล้ว)"
                logger.info(f"[ParkingSummary] show_parking=True format=with_days_diff")
                return message
            else:
                logger.info(f"[ParkingSummary] show_parking=False reason=unexpected_days_diff")
                return None
                
        except Exception as e:
            logger.warning(f"[ParkingSummary] error={e}, show_parking=False")
            return None
    
    def _get_time_diff(self, updated_at: str) -> str:
        """Get human-readable time difference."""
        try:
            updated_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).astimezone(BANGKOK_TZ)
            now = datetime.now(BANGKOK_TZ)
            diff = now - updated_dt
            
            if diff.days == 0:
                return "วันนี้"
            elif diff.days == 1:
                return "เมื่อวาน"
            elif diff.days < 7:
                return f"เมื่อ {diff.days} วันที่แล้ว"
            elif diff.days < 30:
                weeks = diff.days // 7
                return f"เมื่อ {weeks} สัปดาห์ที่แล้ว"
            else:
                return f"เมื่อ {diff.days} วันที่แล้ว"
        except:
            return ""


scheduler = ProactiveScheduler()


async def run_scheduler():
    """Run the scheduler in background."""
    await scheduler.start()


def start_scheduler_background():
    """Start scheduler in background thread/loop."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(run_scheduler())
        else:
            loop.run_until_complete(run_scheduler())
    except RuntimeError:
        asyncio.run(run_scheduler())
