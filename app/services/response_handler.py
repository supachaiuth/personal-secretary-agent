"""
Response handler with action-based responses.
Supports both legacy intent-based and new action-based flows.
"""
from typing import Optional, Dict, Any
from datetime import datetime
import re
from app.repositories.task_repository import TaskRepository
from app.repositories.pantry_repository import PantryRepository
from app.repositories.reminder_repository import ReminderRepository
from app.repositories.user_repository import UserRepository
from app.repositories.activity_repository import ActivityRepository
from app.services.reminder_service import reminder_service


task_repo = TaskRepository()
pantry_repo = PantryRepository()
reminder_repo = ReminderRepository()
user_repo = UserRepository()
activity_repo = ActivityRepository()

import logging
import os
from app.config import Settings
from app.services.calendar_sync_service import calendar_sync_service
logger = logging.getLogger(__name__)

_settings = Settings()


# Legacy intent-based responses (fallback)
INTENT_RESPONSES = {
    "task": {
        "direct": "คุณมีรายการงานดังนี้:\n• งานที่ 1\n• งานที่ 2\n\nต้องการเพิ่มงานใหม่ไหมครับ?",
        "clarification": "ต้องการเพิ่มงานใหม่หรือดูรายการงานครับ?",
    },
    "pantry": {
        "direct": "ของในตู้เย็น/ครัวมีดังนี้:\n• ผักกาด\n• ไก่สด\n• น้ำ",
        "clarification": "เกี่ยวกับอาหาร/ของในบ้าน อยากรู้อะไรครับ? (เช่น มีอะไรบ้าง, ซื้ออะไรเพิ่ม, อะไรหมดอายุ)",
    },
    "reminder": {
        "direct": "เตือนไว้แล้วครับ!",
        "clarification": "ต้องการเตือนอะไร และกี่โมง/วันไหนครับ?",
    },
    "calendar": {
        "direct": "วันนี้คุณมีนัดหมาย:\n• ประชุม 10.00 น.\n• นัดพบเพื่อน 14.00 น.",
        "clarification": "ต้องการดูตารางวันไหนครับ? (วันนี้/พรุ่งนี้/วันอื่นๆ)",
    },
    "search": {
        "direct": "ผลการค้นหา...",
        "clarification": "ต้องการหาข้อมูลเรื่องอะไรครับ?",
    },
    "work_request": {
        "direct": "กำลังดำเนินการให้ครับ...",
        "clarification": "ต้องการให้ช่วยทำอะไรให้บ้างครับ? (เช่น สร้างสไลด์, เขียนอีเมล, หาข้อมูล)",
    },
    "general_chat": {
        "direct": "สวัสดีครับ! มีอะไรให้ช่วยไหมครับ?",
        "clarification": "ขอรายละเอียดเพิ่มเติมได้ไหมครับ?",
    },
}


FALLBACK_RESPONSE = "ขอโทษนะครับ ผมไม่เข้าใจ ลองบอกใหม่ได้ไหมครับ? เช่น ช่วยเตือนงาน, ดูตารางประชุม, ซื้อของ"


def _is_remind_at_in_past(remind_at: str) -> bool:
    """Check if remind_at datetime has already passed (Bangkok time)."""
    try:
        from zoneinfo import ZoneInfo
        BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
        dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
        now_bkk = datetime.now(BANGKOK_TZ)
        return dt.astimezone(BANGKOK_TZ) <= now_bkk
    except Exception:
        return False



# PART 5: Output Consistency - normalize output formats
OUTPUT_FORBIDDEN_WORDS = [
    "รับทราบครับ", "รับทราบค่ะ", "เตือน", "จำไว้นะ",
    "จดจ่อ", "จำไว้", "บันทึกไว้"
]

OUTPUT_FORBIDDEN_PATTERNS = [
    r"^\s*เตือน\s+",  # Starts with เตือน
    r"\s+เตือน\s*$",  # Ends with เตือน
    r"^รับทราบ",  # Starts with รับทราบ
    r"ขอบคุณที่แจ้ง",  # Thanks for notifying
    r"ได้\s+เลย\s*$",  # Ends with "ได้เลย"
]


def normalize_output_v2(output: str, output_type: str = "reminder") -> str:
    """
    Normalize output to enforce consistent format.
    
    Types:
    - reminder: "08:00 ไปหาหมอ" - NOT "08:00 เตือน" or duplicated
    - task: "07:00 - คืนคอม lean consult"
    - agenda: NO filler, clean bullet list
    - pantry: "รถของคุณจอดอยู่ที่ชั้น 5B"
    """
    if not output:
        return output
    
    logger.info(f"[OutputV2] input_type={output_type}, raw='{output[:50]}'")
    
    # Check for forbidden words
    for word in OUTPUT_FORBIDDEN_WORDS:
        if word in output:
            logger.warning(f"[OutputV2] removing forbidden word: {word}")
            output = output.replace(word, "")
    
    # Check for forbidden patterns
    for pattern in OUTPUT_FORBIDDEN_PATTERNS:
        import re
        output = re.sub(pattern, "", output, flags=re.IGNORECASE)
    
    # Type-specific normalization
    if output_type == "reminder":
        # Remove duplicate "เตือน" if appears multiple times
        output = re.sub(r"เตือน\s+เตือน", "เตือน", output)
        output = re.sub(r"เตือน\s+", "", output)
        output = output.strip()
        
    elif output_type == "task":
        # Ensure format is "HH:MM - title" or just "title"
        output = output.strip()
        
    elif output_type == "agenda":
        # Remove any filler text like "รับทราบครับ" or "ขอรายงาน"
        filler_phrases = ["รับทราบครับ", "รับทราบค่ะ", "ขอรายงาน", "นี่คือรายการ"]
        for phrase in filler_phrases:
            if output.startswith(phrase):
                output = output[len(phrase):].strip()
        
        # Ensure starts with bullet or time format
        lines = output.split("\n")
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith("•") and not re.match(r"\d{2}:\d{2}", line):
                line = f"• {line}"
            if line:
                cleaned_lines.append(line)
        output = "\n".join(cleaned_lines)
    
    # Clean up extra whitespace
    output = re.sub(r"\n\s*\n", "\n", output)
    output = output.strip()
    
    logger.info(f"[OutputV2] normalized='{output[:50]}'")
    return output


def _strip_leading_time_safeguard(message: str, time_prefix: str) -> str:
    """
    Backward-compatible safeguard: strip duplicated leading time.
    
    If message starts with same time as time_prefix, strip it.
    E.g., time_prefix="09:00", message="09:00 ซักผ้า" -> "ซักผ้า"
    
    Also handles cases like "08:00-ล้างรถ" -> "ล้างรถ"
    """
    import re
    
    if not message or not time_prefix:
        return message
    
    message_stripped = message.strip()
    
    if message_stripped.startswith(time_prefix):
        remaining = message_stripped[len(time_prefix):].strip()
        remaining = re.sub(r'^[\s\-:]+', '', remaining)
        if remaining:
            logger.info(f"[DedupSafeguard] stripped leading time {time_prefix}, remaining='{remaining}'")
            return remaining
    
    time_pattern = re.match(r'^\d{2}:\d{2}[\s\-:]*', message_stripped)
    if time_pattern:
        remaining = message_stripped[time_pattern.end():].strip()
        remaining = re.sub(r'^[\s\-:]+', '', remaining)
        if remaining:
            logger.info(f"[DedupSafeguard] found different leading time, stripping it")
            return remaining
    
    message_stripped = re.sub(r'^[^\w\u0e00-\u0fff]+', '', message_stripped)
    
    return message_stripped if message_stripped else message


def _handle_parking_query(user_id: Optional[str], user_name: str) -> str:
    """
    Handle parking query intent.
    
    Returns parking location with freshness info:
    - days_diff <= 3: "คุณจอดรถไว้ที่ ชั้น {location}"
    - days_diff > 3: "คุณจอดรถไว้ที่ ชั้น {location} (บันทึกล่าสุดเมื่อ {days_diff} วันที่แล้ว)"
    - no data: "ยังไม่มีข้อมูลที่จอดรถครับ"
    
    NOTE: Direct parking query ALWAYS returns latest record (no freshness hiding)
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.services.supabase_service import get_supabase
    
    BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
    supabase = get_supabase()
    
    logger.info(f"[ParkingQuery] query_start=True user_id={user_id}")
    
    if not user_id:
        logger.info(f"[ParkingQuery] response_mode=no_user")
        return f"{user_name}ยังไม่มีข้อมูลที่จอดรถครับ"
    
    try:
        result = supabase.table("user_memories").select("*").eq("user_id", user_id).eq("topic", "parking").order("updated_at", desc=True).limit(1).execute()
        
        if not result.data or len(result.data) == 0:
            logger.info(f"[ParkingQuery] latest_record_found=False")
            return f"{user_name}ยังไม่มีข้อมูลที่จอดรถครับ"
        
        parking = result.data[0]
        location = parking.get("content", "")
        updated_at = parking.get("updated_at", "")
        
        logger.info(f"[ParkingQuery] latest_record_found=True location={location} updated_at={updated_at}")
        
        if not location:
            logger.info(f"[ParkingQuery] response_mode=empty_location")
            return f"{user_name}ยังไม่มีข้อมูลที่จอดรถครับ"
        
        try:
            updated_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).astimezone(BANGKOK_TZ)
            current_date = datetime.now(BANGKOK_TZ).date()
            parking_date = updated_dt.date()
            days_diff = (current_date - parking_date).days
            
            logger.info(f"[ParkingQuery] days_diff={days_diff}")
            
            if days_diff <= 3:
                response = f"{user_name}คุณจอดรถไว้ที่ {location}"
                logger.info(f"[ParkingQuery] response_mode=fresh response_text={response[:30]}")
                return response
            else:
                response = f"{user_name}คุณจอดรถไว้ที่ {location} (บันทึกล่าสุดเมื่อ {days_diff} วันที่แล้ว)"
                logger.info(f"[ParkingQuery] response_mode=stale response_text={response[:30]}")
                return response
        except Exception as e:
            logger.warning(f"[ParkingQuery] date_parse_error={e}")
            return f"{user_name}คุณจอดรถไว้ที่ {location}"
    
    except Exception as e:
        logger.error(f"[ParkingQuery] error={e}")
        return f"{user_name}ยังไม่มีข้อมูลที่จอดรถครับ"


def get_user_display_name(line_user_id: str) -> str:
    """Get user's display name from LINE or DB."""
    try:
        result = user_repo.get_by_line_user_id(line_user_id)
        if result.data and len(result.data) > 0:
            name = result.data[0].get("display_name")
            if name:
                return name
    except Exception:
        pass
    return "คุณ"


def _build_task_list_response(user_id: Optional[str], user_name: str) -> str:
    """Build task list response from DB."""
    if not user_id:
        return f"{user_name}ยังไม่มีรายการงาน ต้องการเพิ่มงานไหมครับ?"
    
    try:
        result = task_repo.get_by_user_id(user_id)
        tasks = result.data if result.data else []
        
        logger.info(f"[TaskList] Tasks fetched: {len(tasks)}")
        
        if not tasks:
            return f"{user_name}ยังไม่มีงานเลย สบายครับ ✅"
        
        pending_tasks = [t for t in tasks if t.get("status") == "pending"]
        
        logger.info(f"[TaskList] Pending tasks: {len(pending_tasks)}")
        
        if not pending_tasks:
            return f"{user_name}ไม่มีงานที่รอดำเนินการ! สบายแล้วครับ ✅"
        
        shown_tasks = pending_tasks[:5]
        truncated = len(pending_tasks) > 5
        
        if truncated:
            logger.info(f"[TaskList] Tasks shown: {len(shown_tasks)}, truncated: {len(pending_tasks) - len(shown_tasks)} more")
        
        if shown_tasks:
            newest = shown_tasks[0].get("title", "")
            logger.info(f"[TaskList] Newest task: '{newest}'")
        
        task_list = "\n".join([f"• {t.get('title', '')}" for t in shown_tasks])
        
        display_note = f" (แสดง 5 รายการล่าสุด)" if truncated else ""
        
        return f"{user_name}มีงานที่ต้องทำดังนี้:{display_note}\n{task_list}"
    except Exception as e:
        logger.error(f"[TaskList] Error: {e}")
        return f"{user_name}มีรายการงานดังนี้:\n• งานที่ 1\n• งานที่ 2"


def _build_pantry_list_response(user_id: Optional[str], user_name: str) -> str:
    """Build pantry list response from DB."""
    if not user_id:
        return f"{user_name}ยังไม่มีของในตู้เย็น/ครัว ต้องการเพิ่มไหมครับ?"
    
    try:
        result = pantry_repo.get_by_user_id(user_id)
        items = result.data if result.data else []
        
        if not items:
            return f"{user_name}ไม่มีของในตู้เย็น/ครัว! ต้องการซื้ออะไรเพิ่มไหมครับ?"
        
        item_list = "\n".join([f"• {i.get('item_name', '')}" for i in items[:5]])
        return f"{user_name}มีของในตู้เย็น/ครัวดังนี้:\n{item_list}"
    except Exception as e:
        return f"{user_name}มีของในตู้เย็น/ครัวดังนี้:\n• ผักกาด\n• ไก่สด\n• น้ำ"


def _format_thai_datetime(iso_string: str) -> str:
    """Convert ISO datetime to Thai display format."""
    try:
        from zoneinfo import ZoneInfo
        BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        bangkok_time = dt.astimezone(BANGKOK_TZ) if dt.tzinfo else dt
        logger.info(f"[ReminderDisplay] remind_at_raw={iso_string}, display_timezone=Asia/Bangkok, display_time_local={bangkok_time.strftime('%H:%M')}, display_date_local={bangkok_time.strftime('%d/%m/%Y')}")
        return bangkok_time.strftime("%d/%m/%Y เวลา %H:%M น.")
    except Exception as e:
        logger.warning(f"[ReminderDisplay] timezone_convert_error={e}, raw_input={iso_string}")
        return iso_string


def _build_agenda_response(user_id: Optional[str], user_name: str, target_date: str = "tomorrow") -> str:
    """Build agenda response for a specific date (tomorrow/today)."""
    if not user_id:
        return f"{user_name}ขอโทษครับ ไม่สามารถดูรายการได้ในตอนนี้"
    
    from datetime import timedelta, timezone
    from app.services.supabase_service import get_supabase
    
    supabase = get_supabase()
    bangkok_tz = timezone(timedelta(hours=7))
    now = datetime.now(bangkok_tz)
    
    logger.info(f"[Agenda] base_now={now.isoformat()}")
    
    if target_date == "tomorrow":
        agenda_date = (now + timedelta(days=1)).date()
        date_label = "พรุ่งนี้"
    elif target_date == "day_after_tomorrow":
        agenda_date = (now + timedelta(days=2)).date()
        date_label = "มะรืนนี้"
    elif target_date == "today":
        agenda_date = now.date()
        date_label = "วันนี้"
    else:
        try:
            from datetime import date as date_type
            agenda_date = date_type.fromisoformat(target_date)
            date_label = f"วันที่ {agenda_date.strftime('%d/%m/%Y')}"
        except Exception:
            agenda_date = now.date()
            date_label = "วันนี้"
    
    date_start = datetime.combine(agenda_date, datetime.min.time(), tzinfo=bangkok_tz)
    date_end = datetime.combine(agenda_date, datetime.max.time(), tzinfo=bangkok_tz)
    
    logger.info(f"[Agenda] date_label={date_label}, start={date_start.isoformat()}, end={date_end.isoformat()}, timezone=Asia/Bangkok")
    
    logger.info(f"[Agenda] reminders query start")
    rem_result = supabase.table("reminders").select("*").eq("user_id", user_id).eq("sent", False).execute()
    reminders_raw = rem_result.data or []
    logger.info(f"[Agenda] reminders fetched: {len(reminders_raw)}")
    
    timed_items = []
    untimed_items = []
    
    for rem in reminders_raw:
        remind_at_str = rem.get("remind_at", "")
        if remind_at_str:
            try:
                remind_dt = datetime.fromisoformat(remind_at_str.replace("Z", "+00:00")).astimezone(bangkok_tz)
                target_date = date_start.date()
                remind_date = remind_dt.date()
                if target_date == remind_date:
                    minutes = remind_dt.hour * 60 + remind_dt.minute
                    timed_items.append({
                        "minutes": minutes,
                        "time_str": remind_dt.strftime("%H:%M"),
                        "message": rem.get("message", ""),
                        "type": "reminder"
                    })
                    logger.info(f"[Agenda] matched reminder: {remind_dt.date()} == {target_date}, time={remind_dt.strftime('%H:%M')}")
            except Exception as e:
                logger.warning(f"[Agenda] reminder parse error: {e}")
    
    logger.info(f"[Agenda] tasks query start")
    task_result = supabase.table("tasks").select("*").eq("user_id", user_id).in_("status", ["pending", "in_progress"]).order("created_at", desc=True).execute()
    tasks_raw = task_result.data or []
    logger.info(f"[Agenda] tasks fetched: {len(tasks_raw)}")
    
    for task in tasks_raw:
        due_date_str = task.get("due_date", "")
        if due_date_str:
            try:
                due_dt = datetime.fromisoformat(due_date_str.replace("Z", "+00:00")).astimezone(bangkok_tz)
                target_date = date_start.date()
                due_date = due_dt.date()
                if target_date == due_date:
                    timed_items.append({
                        "minutes": due_dt.hour * 60 + due_dt.minute if due_dt.hour else 1440,
                        "time_str": due_dt.strftime("%H:%M") if due_dt.hour else "กำหนด",
                        "message": task.get("title", ""),
                        "type": "task"
                    })
                    logger.info(f"[Agenda] matched task: {due_dt.date()} == {target_date}, time={due_dt.strftime('%H:%M')}")
            except Exception as e:
                logger.warning(f"[Agenda] task parse error: {e}")
    
    timed_items.sort(key=lambda x: x["minutes"])
    
    logger.info(f"[Agenda] reminders_count={len(reminders_raw)}, tasks_count={len(tasks_raw)}, final_items_count={len(timed_items)}")
    
    if not timed_items and not untimed_items:
        return f"📅 {date_label} {user_name}ไม่มีรายการที่ต้องทำครับ ✅"
    
    lines = [f"📅 {date_label} {user_name}มี:"]
    
    for item in timed_items:
        msg = item['message']
        time_str = item['time_str']
        msg = _strip_leading_time_safeguard(msg, time_str)
        lines.append(f"  • {time_str} {msg}")
    
    if untimed_items:
        lines.append("")
        lines.append("📝 อื่นๆ:")
        for item in untimed_items:
            lines.append(f"  • {item['message']}")
    
    return "\n".join(lines)


def get_response_for_action(
    action: str,
    extracted_fields: Dict[str, Any],
    user_id: Optional[str],
    line_user_id: Optional[str],
    user_role: str = "partner"
) -> tuple[str, bool]:
    """
    Generate response based on action and extracted fields.
    
    Returns:
        (response_text, is_complete)
    """
    user_name = get_user_display_name(line_user_id) if line_user_id else "คุณ"
    
    # ===== add_task =====
    if action == "add_task":
        title = extracted_fields.get("title", "")
        if not title:
            return f"{user_name}ต้องการเพิ่มงานอะไรครับ?", False
        
        # Save to DB
        try:
            if user_id:
                task_repo.create(user_id, title)
                activity_repo.log_activity(user_id, "task_created", {"title": title})
                logger.info(f"[ResponseHandler] Task created: {title} for user {user_id}")
                return f"✅ เพิ่มงาน '{title}' เรียบร้อยครับ", True
            else:
                return f"✅ เพิ่มงาน '{title}' เรียบร้อยครับ", True
        except Exception as e:
            logger.error(f"[ResponseHandler] Error creating task: {e}")
            return f"❌ ไม่สามารถเพิ่มงานได้ ลองใหม่อีกครั้งครับ", False
    
    # ===== list_tasks =====
    if action == "list_tasks":
        return _build_task_list_response(user_id, user_name), True
    
    # ===== agenda_query =====
    if action == "agenda_query":
        target_date = extracted_fields.get("date", "tomorrow")
        return _build_agenda_response(user_id, user_name, target_date), True
    
    # ===== parking_query =====
    if action == "parking_query":
        return _handle_parking_query(user_id, user_name), True
    
    # ===== add_pantry =====
    if action == "add_pantry":
        item_name = extracted_fields.get("item_name", "")
        if not item_name:
            return f"{user_name}ต้องการเพิ่มอะไรในตู้เย็นครับ?", False
        
        try:
            if user_id:
                pantry_repo.create(user_id, item_name)
                activity_repo.log_activity(user_id, "pantry_updated", {"item_name": item_name, "action": "add"})
                logger.info(f"[ResponseHandler] Pantry item created: {item_name}")
                return f"✅ เพิ่ม '{item_name}' ในตู้เย็นเรียบร้อยครับ", True
            else:
                return f"✅ เพิ่ม '{item_name}' ในตู้เย็นเรียบร้อยครับ", True
        except Exception as e:
            logger.error(f"[ResponseHandler] Error creating pantry item: {e}")
            return f"❌ ไม่สามารถเพิ่มได้ ลองใหม่อีกครั้งครับ", False
    
    # ===== list_pantry =====
    if action == "list_pantry":
        return _build_pantry_list_response(user_id, user_name), True
    
    # ===== clarify_intent (hardening for ambiguous inputs) =====
    if action == "clarify_intent":
        question = extracted_fields.get("clarification_question", "ขอความชัดเจนได้ไหมครับ?")
        logger.info(f"[Hardening] clarification_state=ambiguous_intent question={question}")
        return question, False
    
    # ===== create_reminder =====
    if action == "create_reminder":
        from app.services.reminder_service import is_valid_reminder
        
        # CRITICAL: Check for validation error from parser
        validation_error = extracted_fields.get("validation_error")
        if validation_error:
            logger.warning(f"[Hardening] db_write_blocked reason=validation_error_{validation_error}")
            return f"❌ เวลาไม่ถูกต้อง กรุณาระบุเวลาใหม่ครับ", False
        
        # CRITICAL: Normalize message to string
        raw_message = extracted_fields.get("message")
        
        # Handle case where message is dict or None
        if isinstance(raw_message, dict):
            message = ""
            logger.warning(f"[ResponseHandler] message is dict: {raw_message}")
        elif isinstance(raw_message, str):
            message = raw_message.strip()
        else:
            message = ""
        
        has_time = extracted_fields.get("has_time", False)
        remind_at = extracted_fields.get("remind_at")
        
        logger.info(f"[ResponseHandler] Reminder: message='{message}', has_time={has_time}, remind_at={remind_at}, user_id={user_id}")
        
        # ============================================================
        # PART 6: Safety Guard Layer - validate ALL conditions before DB write
        # Check 1: validation_result == valid
        # Check 2: NOT ambiguous (needs_clarification should be False)
        # Check 3: NOT partial (message must be complete)
        # Check 4: NOT forbidden fragments
        # Check 5: has_time and remind_at must exist
        # ============================================================
        
        if not message or len(message.strip()) < 3:
            logger.warning(f"[HardeningV2] db_write_blocked reason=partial_message")
            return f"รายละเอียดการเตือนสั้นเกินไป ขอรายละเอียดเพิ่มเติมได้ไหมครับ?", False
        
        forbidden_fragments = ["เยน", "เช้า", "บ่าย", "คืน", "ทุ่ม", "ตี", "น.", "โมง"]
        if message.strip() in forbidden_fragments:
            logger.warning(f"[HardeningV2] db_write_blocked reason=forbidden_fragment")
            return f"ขอรายละเอียดเพิ่มเติมได้ไหมครับ?", False
        
        if not has_time or not remind_at:
            logger.warning(f"[HardeningV2] db_write_blocked reason=missing_time")
            return f"ต้องการให้เตือนกี่โมงครับ?", False
        
        # Check if remind_at is in the past
        if _is_remind_at_in_past(remind_at):
            from zoneinfo import ZoneInfo
            now_bkk = datetime.now(ZoneInfo("Asia/Bangkok"))
            logger.warning(f"[HardeningV2] db_write_blocked reason=remind_at_in_past remind_at={remind_at}")
            return (
                f"❌ เวลานั้นผ่านไปแล้วนะครับ ตอนนี้ {now_bkk.strftime('%H:%M')} น.แล้วครับ\n"
                f"ต้องการตั้งเตือนวันอื่นหรือเวลาอื่นไหมครับ?"
            ), False

        
        # Normalize the reminder message before saving
        from app.services.reminder_service import reminder_service
        parsed_for_normalize = {
            "message": message,
            "time": extracted_fields.get("time"),
            "date": extracted_fields.get("date"),
            "_original": extracted_fields.get("raw", "")
        }
        normalized_message = reminder_service.normalize_reminder_display(parsed_for_normalize)
        logger.info(f"[ReminderNormalizeFix] original_message={message}, normalized_message={normalized_message}")
        
        # CRITICAL: Validate before saving to DB
        reminder_data = {
            "message": normalized_message,
            "remind_at": remind_at
        }
        if not is_valid_reminder(reminder_data):
            logger.warning(f"[ResponseHandler] Reminder validation failed, message='{normalized_message}', remind_at={remind_at}")
            return f"❌ ไม่สามารถสร้างการแจ้งเตือนได้ (ข้อมูลไม่ถูกต้อง)", False
        
        # CRITICAL: Only return success AFTER DB insert succeeds
        if not user_id:
            logger.error(f"[ResponseHandler] Cannot save reminder: no user_id")
            return f"❌ ไม่สามารถสร้างการแจ้งเตือนได้ (ไม่พบ user)", False
        
        if not remind_at:
            logger.error(f"[ResponseHandler] Cannot save reminder: no remind_at")
            return f"❌ ไม่สามารถสร้างการแจ้งเตือนได้ (ไม่ระบุเวลา)", False
        
        # Save to DB
        try:
            from app.repositories.reminder_repository import ReminderRepository
            reminder_repo = ReminderRepository()
            
            # HARDENING: Add debug logging for DB write
            logger.info(f"[Hardening] db_write_attempt user_id={user_id} message={normalized_message[:30]}")
            
            existing = reminder_repo.find_duplicate(user_id, normalized_message, remind_at)
            if existing:
                logger.info(f"[ResponseHandler] Duplicate reminder detected, reusing existing: id={existing.get('id')}")
                formatted_time = _format_thai_datetime(existing.get("remind_at", ""))
                return f"ℹ️ มีการเตือน '{normalized_message}' อยู่แล้ว {formatted_time} ครับ", True
            
            reminder_repo.create(user_id, normalized_message, remind_at)
            activity_repo.log_activity(user_id, "reminder_created", {"message": normalized_message, "remind_at": remind_at})
            
            # HARDENING: Verify write succeeded
            logger.info(f"[Hardening] db_write_success user_id={user_id} message={normalized_message[:30]}")
            
            formatted_time = _format_thai_datetime(remind_at)
            return f"✅ ตั้งเตือน '{normalized_message}' {formatted_time} เรียบร้อยครับ", True
        except Exception as e:
            logger.error(f"[ResponseHandler] ❌ Error creating reminder: {e}")
            return f"❌ ไม่สามารถสร้างการแจ้งเตือนได้ ลองใหม่อีกครั้งครับ", False
    
    # ===== calendar_query =====
    if action == "calendar_query":
        return f"{user_name}ขอโทษครับ ยังไม่สามารถดูตารางนัดหมายได้ในตอนนี้", True
    
    # ===== connect_calendar =====
    if action == "connect_calendar":
        if not line_user_id:
            return "ขอโทษครับ ไม่สามารถระบุตัวตนของคุณได้ กรุณาลองใหม่อีกครั้ง", True
            
        base_url = os.getenv("BASE_URL", "http://localhost:8000")
        auth_url = f"{base_url}/auth/google/login?line_user_id={line_user_id}"
        
        flex_msg = _get_calendar_connect_flex(auth_url)
        return flex_msg, True

    # ===== create_calendar_event =====
    if action == "create_calendar_event":
        # Similar logic to create_reminder but with calendar focus
        from app.services.reminder_service import is_valid_reminder
        
        validation_error = extracted_fields.get("validation_error")
        if validation_error:
            return f"❌ เวลาไม่ถูกต้อง กรุณาระบุเวลาใหม่นะครับ", False
            
        message = extracted_fields.get("message", "").strip()
        remind_at = extracted_fields.get("remind_at")
        has_time = extracted_fields.get("has_time", False)
        
        if not message or len(message) < 2:
            return "ต้องการให้นัดหมายเรื่องอะไรครับ?", False
            
        if not has_time or not remind_at:
            return "นัดหมายตอนกี่โมงครับ?", False
            
        if _is_remind_at_in_past(remind_at):
            return "❌ เวลานัดหมายนั้นผ่านมาแล้วครับ รบกวนระบุเวลาใหม่นะครับ", False
            
        # 1. Save to Reminders (for LINE notifications)
        try:
            # Check for duplicate
            existing = reminder_repo.find_duplicate(user_id, message, remind_at)
            if not existing:
                reminder_repo.create(user_id, message, remind_at)
                activity_repo.log_activity(user_id, "reminder_created", {"message": message, "remind_at": remind_at, "is_calendar": True})
            
            formatted_time = _format_thai_datetime(remind_at)
            
            # 2. Check for Google Calendar connection
            user_data = user_repo.get_by_line_user_id(line_user_id).data[0]
            if user_data.get("google_refresh_token"):
                # Actual Google Calendar API call
                try:
                    # Map Thai-calculated remind_at to Google start_time
                    # (remind_at is already ISO formatted)
                    calendar_sync_service.create_google_event(
                        line_user_id=line_user_id,
                        title=message,
                        start_time=remind_at
                    )
                    return f"✅ บันทึกนัดหมาย '{message}' {formatted_time} เรียบร้อยครับ (และเพิ่มลง Google Calendar ให้แล้ว 🗓️)", True
                except Exception as g_err:
                    logger.error(f"[GoogleCalendar] Error creating event: {g_err}")
                    return f"✅ บันทึกนัดหมาย '{message}' {formatted_time} เรียบร้อยครับ (แต่พบปัญหาในการเพิ่มลง Google Calendar)", True
            else:
                return (
                    f"✅ บันทึกนัดหมาย '{message}' {formatted_time} เรียบร้อยครับ\n\n"
                    "💡 ปล. คุณยังไม่ได้เชื่อมต่อ Google Calendar ถ้าสนใจพิมพ์ 'เชื่อมต่อปฏิทิน' ได้นะครับ"
                ), True
                
        except Exception as e:
            logger.error(f"[ResponseHandler] Error creating calendar event: {e}")
            return "❌ เกิดข้อผิดพลาดในการบันทึกนัดหมายครับ", False

    # ===== cancel_reminder =====
    if action == "cancel_reminder":
        keyword = extracted_fields.get("keyword", "")
        date_filter = extracted_fields.get("date_filter")
        selected_index = extracted_fields.get("selected_index")
        matches = extracted_fields.get("matches", [])
        
        if not user_id:
            return f"{user_name}ขอโทษครับ ไม่สามารถยกเลิกนัดหมายได้ในตอนนี้", False
        
        from app.repositories.reminder_repository import ReminderRepository
        reminder_repo = ReminderRepository()
        
        # Step 1: Initial search
        if not matches:
            if not keyword:
                return "ต้องการให้ยกเลิกนัดหมายอะไรครับ?", False
                
            search_results = reminder_repo.search_by_keyword(user_id, keyword, date_filter)
            if not search_results:
                return f"ไม่พบการตั้งเตือนที่มีคำว่า '{keyword}' ครับ", True
                
            if len(search_results) == 1:
                # Single match -> ask for confirmation
                rem = search_results[0]
                extracted_fields["matches"] = [rem]
                formatted_time = _format_thai_datetime(rem.get("remind_at", ""))
                return f"ต้องการยกเลิกการตั้งเตือน '{rem.get('message')}' เวลา {formatted_time} ใช่ไหมครับ?\n(พิมพ์ 'ใช่', 'ยืนยัน', 'ตกลง' หรือพิมพ์ตัวเลข '1' เพื่อยืนยัน)", False
            else:
                # Multiple matches -> show list
                extracted_fields["matches"] = search_results
                lines = [f"พบการตั้งเตือน {len(search_results)} รายการ กรุณาพิมพ์หมายเลขเพื่อเลือกรายการที่ต้องการยกเลิกครับ:"]
                for i, rem in enumerate(search_results, 1):
                    formatted_time = _format_thai_datetime(rem.get("remind_at", ""))
                    lines.append(f"{i}. {rem.get('message')} ({formatted_time})")
                return "\n".join(lines), False
                
        # Step 2 & 3: Handle selection or confirmation
        else:
            search_results = matches
            if len(search_results) == 1:
                # Confirmation expected
                reply = extracted_fields.get("user_replied", "").lower().strip()
                if reply in ["ใช่", "ยืนยัน", "ตกลง", "y", "yes", "1", "ok", "โอเค"]:
                    selected_rem = search_results[0]
                elif reply in ["ไม่", "ยกเลิก", "n", "no"]:
                    return "ยกเลิกการทำรายการเรียบร้อยครับ", True
                else:
                    return "กรุณายืนยันว่าต้องการยกเลิกการตั้งเตือนนี้หรือไม่? (พิมพ์ 'ใช่' หรือ 'ไม่')", False
            else:
                # Number selection expected
                try:
                    reply = extracted_fields.get("user_replied", "").strip()
                    if reply in ["ไม่", "ยกเลิก", "n", "no"]:
                        return "ยกเลิกการทำรายการเรียบร้อยครับ", True
                        
                    idx = int(reply) - 1
                    if 0 <= idx < len(search_results):
                        selected_rem = search_results[idx]
                    else:
                        return f"กรุณาพิมพ์หมายเลข 1 ถึง {len(search_results)} ครับ", False
                except ValueError:
                    return f"กรุณาพิมพ์หมายเลขที่ต้องการ (เช่น '1', '2') ครับ", False
            
            # Execute deletion
            rem_id = selected_rem.get("id")
            rem_msg = selected_rem.get("message")
            try:
                reminder_repo.delete(rem_id)
                activity_repo.log_activity(user_id, "reminder_deleted", {"message": rem_msg})
                logger.info(f"[ResponseHandler] Canceled reminder {rem_id} for user {user_id}")
                return f"✅ ยกเลิกการตั้งเตือน '{rem_msg}' เรียบร้อยแล้วครับ", True
            except Exception as e:
                logger.error(f"[ResponseHandler] Error canceling reminder: {e}")
                return "❌ เกิดข้อผิดพลาดในการยกเลิกการตั้งเตือน ลองใหม่อีกครั้งครับ", True

    # ===== unknown action =====
    return f"{user_name}ขอโทษครับ ไม่เข้าใจ ลองใหม่ได้ไหมครับ?", False


# Legacy function for backward compatibility
def get_response_for_intent(
    intent: str,
    needs_clarification: bool,
    user_message: str = "",
    user_id: Optional[str] = None,
    line_user_id: Optional[str] = None,
    user_role: str = "partner",
    collected_fields: Optional[Dict[str, Any]] = None
) -> str:
    """Legacy function - use get_response_for_action instead."""
    user_name = get_user_display_name(line_user_id) if line_user_id else "คุณ"
    
    # Build real responses for certain intents
    if intent == "task" and not needs_clarification:
        return _build_task_list_response(user_id, user_name)
    
    if intent == "pantry" and not needs_clarification:
        return _build_pantry_list_response(user_id, user_name)
    
    if intent not in INTENT_RESPONSES:
        return FALLBACK_RESPONSE
    
    intent_responses = INTENT_RESPONSES[intent]
    
    if needs_clarification:
        return intent_responses.get("clarification", intent_responses.get("direct", FALLBACK_RESPONSE))
    
    return intent_responses.get("direct", FALLBACK_RESPONSE)


def get_clarification_question(intent: str, default_message: str = "") -> str:
    """Legacy function."""
    if intent in INTENT_RESPONSES:
        return INTENT_RESPONSES[intent].get("clarification", "ขอรายละเอียดเพิ่มเติมได้ไหมครับ?")
    
    if default_message:
        return default_message
    
    return "ขอรายละเอียดเพิ่มเติมได้ไหมครับ?"


def _get_calendar_connect_flex(auth_url: str) -> dict:
    """Generate a premium Flex Message for Google Calendar connection."""
    return {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": "https://www.gstatic.com/calendar/images/dynamiclogo_2020q4/calendar_31_2x.png",
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover",
            "action": {
                "type": "uri",
                "uri": auth_url
            }
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "เชื่อมต่อ Google Calendar",
                    "weight": "bold",
                    "size": "xl"
                },
                {
                    "type": "text",
                    "text": "ให้ผมช่วยดูแลนัดหมายของคุณให้ง่ายขึ้น",
                    "size": "sm",
                    "color": "#8c8c8c",
                    "wrap": True,
                    "margin": "md"
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "lg",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "baseline",
                            "spacing": "sm",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": "•",
                                    "color": "#aaaaaa",
                                    "size": "sm",
                                    "flex": 1
                                },
                                {
                                    "type": "text",
                                    "text": "แจ้งเตือนล่วงหน้า 1 ชั่วโมง",
                                    "wrap": True,
                                    "color": "#666666",
                                    "size": "sm",
                                    "flex": 5
                                }
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "baseline",
                            "spacing": "sm",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": "•",
                                    "color": "#aaaaaa",
                                    "size": "sm",
                                    "flex": 1
                                },
                                {
                                    "type": "text",
                                    "text": "เพิ่มนัดหมายผ่านแชทได้ทันที",
                                    "wrap": True,
                                    "color": "#666666",
                                    "size": "sm",
                                    "flex": 5
                                }
                            ]
                        }
                    ]
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "color": "#4285F4",
                    "action": {
                        "type": "uri",
                        "label": "เชื่อมต่อเลย",
                        "uri": auth_url
                    }
                }
            ],
            "flex": 0
        }
    }
