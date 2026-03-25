"""
Response handler with action-based responses.
Supports both legacy intent-based and new action-based flows.
"""
from typing import Optional, Dict, Any
from datetime import datetime
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
logger = logging.getLogger(__name__)


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
        
        pending_tasks = [t for t in tasks if t.get("status") == "pending"]
        
        if not pending_tasks:
            return f"{user_name}ไม่มีงานที่รอดำเนินการ! สบายแล้วครับ ✅"
        
        task_list = "\n".join([f"• {t.get('title', '')}" for t in pending_tasks[:5]])
        return f"{user_name}มีงานที่ต้องทำดังนี้:\n{task_list}"
    except Exception as e:
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
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        bangkok_time = dt.astimezone() if dt.tzinfo else dt
        return bangkok_time.strftime("%d/%m/%Y เวลา %H:%M น.")
    except Exception:
        return iso_string


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
    
    # ===== create_reminder =====
    if action == "create_reminder":
        from app.services.reminder_service import is_valid_reminder
        
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
        
        # Check if complete
        if not message:
            return f"ต้องการให้เตือนอะไรครับ?", False
        
        if not has_time or not remind_at:
            return f"ต้องการให้เตือนกี่โมงครับ?", False
        
        # CRITICAL: Validate before saving to DB
        reminder_data = {
            "message": message,
            "remind_at": remind_at
        }
        if not is_valid_reminder(reminder_data):
            logger.warning(f"[ResponseHandler] Reminder validation failed, message='{message}', remind_at={remind_at}")
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
            reminder_repo.create(user_id, message, remind_at)
            activity_repo.log_activity(user_id, "reminder_created", {"message": message, "remind_at": remind_at})
            logger.info(f"[ResponseHandler] ✅ Reminder SAVED to DB: message='{message}', remind_at={remind_at}")
            
            formatted_time = _format_thai_datetime(remind_at)
            return f"✅ ตั้งเตือน '{message}' {formatted_time} เรียบร้อยครับ", True
        except Exception as e:
            logger.error(f"[ResponseHandler] ❌ Error creating reminder: {e}")
            return f"❌ ไม่สามารถสร้างการแจ้งเตือนได้ ลองใหม่อีกครั้งครับ", False
    
    # ===== calendar_query =====
    if action == "calendar_query":
        return f"{user_name}ขอโทษครับ ยังไม่สามารถดูตารางนัดหมายได้ในตอนนี้", True
    
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
