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
from datetime import datetime, timedelta, time, date
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

from supabase import Client
from app.services.supabase_service import get_supabase
from app.services.line_service import push_message
from app.services.reminder_service import is_valid_reminder, INVALID_PREFIX

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
        self._last_morning_run: Optional[date] = None
        self._last_advance_run: Optional[date] = None
        self._last_daily_run: Optional[date] = None
    
    def reset_daily_state(self):
        """Reset daily run state - useful for testing"""
        self._last_morning_run = None
        self._last_advance_run = None
        self._last_daily_run = None
        logger.info("[SCHEDULER] Daily state reset for testing")
    
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
            
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            
            await asyncio.sleep(self.check_interval)
    
    def stop(self):
        """Stop the scheduler."""
        self.is_running = False
        logger.info("Proactive scheduler stopped")
    
    async def check_and_run_morning_summary(self, now_bkk: datetime, today: date):
        """Run morning summary at configured time (default 07:45)."""
        current_time = now_bkk.time()
        target_time_default = datetime.strptime("07:45", "%H:%M").time()
        window_minutes = 2
        window_end_time = (datetime.combine(datetime.today(), target_time_default) + timedelta(minutes=window_minutes)).time()
        
        logger.info(f"[SCHEDULER] morning_summary CHECK: current={current_time} target={target_time_default} window_end={window_end_time} last_run={self._last_morning_run}")
        
        # Skip if too early
        if current_time < target_time_default:
            logger.info(f"[SCHEDULER] morning_summary SKIP: reason=too_early current={current_time} < target={target_time_default}")
            return
        
        # Skip if missed window
        if current_time > window_end_time:
            logger.info(f"[SCHEDULER] morning_summary SKIP: reason=missed_window current={current_time} > window_end={window_end_time}")
            return
        
        # Skip if already ran today
        if self._last_morning_run == today:
            logger.info(f"[SCHEDULER] morning_summary SKIP: reason=already_ran_today")
            return
        
        users = self._get_users_with_morning_enabled()
        
        if not users:
            logger.info(f"[SCHEDULER] morning_summary SKIP: reason=no_users")
            return
        
        logger.info(f"[SCHEDULER] morning_summary EXECUTE: reason=within_window current={current_time} target={target_time_default} window_end={window_end_time}")
        
        users_run = False
        for user in users:
            user_id = user.get("id")
            user_time = user.get("morning_summary_time") or "07:45"
            
            logger.info(f"[SCHEDULER] morning_summary USER: user_id={user_id} user_target={user_time}")
            
            target_time = parse_time_safe(user_time, "07:45")
            user_window_end = (datetime.combine(datetime.today(), target_time) + timedelta(minutes=window_minutes)).time()
            
            if target_time <= current_time <= user_window_end:
                logger.info(f"[SCHEDULER] morning_summary USER_EXECUTE: user_id={user_id} in_window")
                try:
                    success = await self._run_morning_summary_for_user(user)
                    if success:
                        logger.info(f"[SCHEDULER] morning_summary SUCCESS: user_id={user_id}")
                        users_run = True
                    else:
                        logger.warning(f"[SCHEDULER] morning_summary FAILED: user_id={user_id} push_failed")
                except Exception as e:
                    logger.error(f"[SCHEDULER] morning_summary ERROR: user_id={user_id} error={e}")
            else:
                logger.info(f"[SCHEDULER] morning_summary USER_SKIP: user_id={user_id} outside_window")
        
        # Only mark as run after successful send
        if users_run:
            self._last_morning_run = today
            logger.info(f"[SCHEDULER] morning_summary MARKED_RUN: today={today}")
    
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
        """Run daily summary at configurable time (default 20:00)."""
        current_time = now_bkk.time()
        target_time_default = datetime.strptime("20:00", "%H:%M").time()
        window_minutes = 2
        window_end_time = (datetime.combine(datetime.today(), target_time_default) + timedelta(minutes=window_minutes)).time()
        
        logger.info(f"[SCHEDULER] daily_summary CHECK: current={current_time} target={target_time_default} window_end={window_end_time} last_run={self._last_daily_run}")
        
        # Skip if too early
        if current_time < target_time_default:
            logger.info(f"[SCHEDULER] daily_summary SKIP: reason=too_early current={current_time} < target={target_time_default}")
            return
        
        # Skip if missed window
        if current_time > window_end_time:
            logger.info(f"[SCHEDULER] daily_summary SKIP: reason=missed_window current={current_time} > window_end={window_end_time}")
            return
        
        # Skip if already ran today
        if self._last_daily_run == today:
            logger.info(f"[SCHEDULER] daily_summary SKIP: reason=already_ran_today")
            return
        
        users = self._get_users_with_daily_enabled()
        
        if not users:
            logger.info(f"[SCHEDULER] daily_summary SKIP: reason=no_users")
            return
        
        logger.info(f"[SCHEDULER] daily_summary EXECUTE: reason=within_window current={current_time} target={target_time_default} window_end={window_end_time}")
        
        users_run = False
        for user in users:
            user_id = user.get("id")
            user_time = user.get("daily_summary_time") or "20:00"
            
            logger.info(f"[SCHEDULER] daily_summary USER: user_id={user_id} user_target={user_time}")
            
            target_time = parse_time_safe(user_time, "20:00")
            user_window_end = (datetime.combine(datetime.today(), target_time) + timedelta(minutes=window_minutes)).time()
            
            if target_time <= current_time <= user_window_end:
                logger.info(f"[SCHEDULER] daily_summary USER_EXECUTE: user_id={user_id} in_window")
                try:
                    success = await self._run_daily_summary_for_user(user)
                    if success:
                        logger.info(f"[SCHEDULER] daily_summary SUCCESS: user_id={user_id}")
                        users_run = True
                    else:
                        logger.warning(f"[SCHEDULER] daily_summary FAILED: user_id={user_id} push_failed")
                except Exception as e:
                    logger.error(f"[SCHEDULER] daily_summary ERROR: user_id={user_id} error={e}")
            else:
                logger.info(f"[SCHEDULER] daily_summary USER_SKIP: user_id={user_id} outside_window")
        
        # Only mark as run after successful send
        if users_run:
            self._last_daily_run = today
            logger.info(f"[SCHEDULER] daily_summary MARKED_RUN: today={today}")
    
    async def check_due_reminders(self):
        """Check and send due reminders."""
        try:
            result = supabase.table("reminders").select("*").eq("sent", False).lte("remind_at", datetime.now(BANGKOK_TZ).isoformat()).execute()
            
            if not result.data:
                return
            
            for reminder in result.data:
                if not is_valid_reminder(reminder):
                    logger.warning(f"[Due Reminder] Skipping invalid reminder id={reminder.get('id')}")
                    continue
                
                user_id = reminder.get("user_id")
                message = reminder.get("message")
                reminder_id = reminder.get("id")
                
                user_result = supabase.table("users").select("line_user_id, display_name").eq("id", user_id).execute()
                if not user_result.data:
                    continue
                
                line_user_id = user_result.data[0].get("line_user_id")
                display_name = user_result.data[0].get("display_name", "คุณ")
                
                if line_user_id:
                    text = f"🔔 พลาดไม่ได้!\n\n{message}"
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
    
    async def _run_morning_summary_for_user(self, user: Dict):
        """Generate and send morning summary for a user."""
        user_id = user.get("id")
        line_user_id = user.get("line_user_id")
        display_name = user.get("display_name", "คุณ")
        
        if not line_user_id:
            return
        
        today_start = datetime.now(BANGKOK_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        tasks_result = supabase.table("tasks").select("*").eq("user_id", user_id).in_("status", ["pending", "in_progress"]).execute()
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
        
        message = self._format_morning_summary(display_name, pending_tasks, today_reminders, memories)
        
        if push_message(line_user_id, message):
            supabase.table("summary_logs").insert({
                "user_id": user_id,
                "summary_type": "morning",
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
        
        tasks_created = sum(1 for a in (activities_result.data or []) if a.get("activity_type") == "task_created")
        reminders_created = sum(1 for a in (activities_result.data or []) if a.get("activity_type") == "reminder_created")
        pantry_updates = sum(1 for a in (activities_result.data or []) if a.get("activity_type") == "pantry_updated")
        
        upcoming_result = supabase.table("reminders").select("*").eq("user_id", user_id).eq("sent", False).gte("remind_at", datetime.now(BANGKOK_TZ).isoformat()).execute()
        upcoming = upcoming_result.data or []
        
        upcoming = deduplicate_reminders(filter_valid_reminders(upcoming))
        logger.info(f"[Daily Summary] Valid upcoming reminders for user {user_id}: {len(upcoming)}")
        
        message = self._format_daily_summary(display_name, tasks_created, reminders_created, pantry_updates, upcoming)
        
        if push_message(line_user_id, message):
            supabase.table("summary_logs").insert({
                "user_id": user_id,
                "summary_type": "daily",
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
    
    def _format_morning_summary(self, display_name: str, tasks: List[Dict], reminders: List[Dict], memories: List[Dict]) -> str:
        """Format morning summary message."""
        lines = ["🌅 สรุปเช้านี้", ""]
        
        lines.append("📋 วันนี้:")
        
        if tasks:
            task_list = "\n".join([f"  • {t.get('title', '')}" for t in tasks[:5]])
            lines.append(f"  งาน:\n{task_list}")
        else:
            lines.append("  ไม่มีงานที่ต้องทำ")
        
        if reminders:
            rem_list = "\n".join([f"  • {r.get('message', '')}" for r in reminders[:3]])
            lines.append(f"  เตือน:\n{rem_list}")
        
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
    
    def _format_daily_summary(self, display_name: str, tasks_created: int, reminders_created: int, pantry_updates: int, upcoming: List[Dict]) -> str:
        """Format daily summary message."""
        lines = ["🌙 สรุปประจำวัน", ""]
        
        lines.append("📊 วันนี้:")
        lines.append(f"  • งานใหม่: {tasks_created}")
        lines.append(f"  • เตือนใหม่: {reminders_created}")
        lines.append(f"  • อัปเดตตู้เย็น: {pantry_updates}")
        
        if upcoming:
            lines.append("")
            lines.append("📅 วันข้างหน้า:")
            for u in upcoming[:5]:
                remind_at = u.get("remind_at", "")
                if remind_at:
                    dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00")).astimezone(BANGKOK_TZ)
                    date_str = dt.strftime("%d/%m %H:%M")
                    lines.append(f"  • {date_str} - {u.get('message', '')}")
        
        lines.append("")
        lines.append("รับทราบครับ ✅")
        
        return "\n".join(lines)
    
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
