"""
Command detector with hard rules BEFORE LLM classification.
Implements deterministic behavior for common commands.
"""
import re
import logging
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Explicit command patterns - MUST be checked first
# Format: (pattern, action, extraction_key)
EXPLICIT_COMMANDS = [
    # Task commands
    (r"^เพิ่มงาน\s+(.+)$", "add_task", "title"),
    (r"^เพิ่ม\s+(.+)$", "add_task", "title"),
    (r"^ดูรายการงาน$", "list_tasks", None),
    (r"^งานมีอะไรบ้าง$", "list_tasks", None),
    (r"^งานที่ต้องทำ$", "list_tasks", None),
    (r"^มีงานอะไรบ้าง$", "list_tasks", None),
    
    # Reminder commands
    (r"^(เตือน|แจ้งเตือน)\s*(.+)$", "create_reminder", "raw"),
    
    # Calendar commands (only explicit calendar keywords)
    (r"^(ประชุม|นัดหมาย|ตารางประชุม)\s*(.*)$", "calendar_query", "query"),
    (r"^(ตารางวันนี้|ตารางพรุ่งนี้)\s*$", "calendar_query", "query"),
    
    # Pantry commands
    (r"^(ของในตู้เย็น|ในตู้เย็นมีอะไร)\s*$", "list_pantry", None),
    (r"^(ซื้อ|เพิ่ม)\s*([^\s].+)$", "add_pantry", "item"),
]


def detect_command(user_message: str) -> Optional[Dict[str, Any]]:
    """
    Detect explicit commands using keyword/regex matching.
    
    Returns:
        dict with keys: action, extracted_fields, needs_clarification
        OR None if no explicit command matched
    """
    message = user_message.strip()
    lower_message = message.lower()
    
    logger.info(f"[CommandDetector] Processing: {message}")
    
    # 1. Task: Add new task
    # Pattern: "เพิ่มงาน <text>" or "เพิ่ม <text>"
    match = re.match(r"^เพิ่มงาน\s+(.+)$", message)
    if match:
        title = match.group(1).strip()
        logger.info(f"[CommandDetector] Detected: add_task, title={title}")
        return {
            "action": "add_task",
            "extracted_fields": {"title": title},
            "needs_clarification": False,
            "source": "explicit_command"
        }
    
    # Pattern: "เพิ่ม <text>" (without "งาน")
    match = re.match(r"^เพิ่ม\s+([^\s].+)$", message)
    if match:
        title = match.group(1).strip()
        logger.info(f"[CommandDetector] Detected: add_task (short), title={title}")
        return {
            "action": "add_task",
            "extracted_fields": {"title": title},
            "needs_clarification": False,
            "source": "explicit_command"
        }
    
    # 2. Task: List tasks
    list_patterns = [
        r"^ดูรายการงาน$",
        r"^งานมีอะไรบ้าง$",
        r"^งานที่ต้องทำ$",
        r"^มีงานอะไรบ้าง$",
    ]
    for pattern in list_patterns:
        if re.match(pattern, message):
            logger.info(f"[CommandDetector] Detected: list_tasks")
            return {
                "action": "list_tasks",
                "extracted_fields": {},
                "needs_clarification": False,
                "source": "explicit_command"
            }
    
    # 3. Reminder: Create reminder
    # Pattern: "เตือน <message>" or "เตือนฉัน <message>" or "แจ้งเตือน <message>"
    reminder_match = re.match(r"^(เตือน|แจ้งเตือน)\s*(.*)$", message)
    if reminder_match:
        raw_text = reminder_match.group(2).strip()
        logger.info(f"[CommandDetector] Detected: create_reminder, raw={raw_text}")
        
        # Parse time from reminder message
        from app.services.reminder_service import reminder_service
        parsed = reminder_service.parse_reminder_message(raw_text)
        
        # Calculate remind_at if we have date and time
        remind_at = None
        if parsed.get("date") and parsed.get("time"):
            remind_at = reminder_service.calculate_remind_at(parsed.get("date"), parsed.get("time"))
        
        needs_clarification = not parsed.get("has_time") or not remind_at
        
        logger.info(f"[CommandDetector] Reminder parsed: {parsed}, needs_clarification={needs_clarification}, remind_at={remind_at}")
        
        return {
            "action": "create_reminder",
            "extracted_fields": {
                "message": parsed.get("message", raw_text),
                "date": parsed.get("date"),
                "time": parsed.get("time"),
                "has_time": parsed.get("has_time", False),
                "remind_at": remind_at
            },
            "needs_clarification": needs_clarification,
            "source": "explicit_command"
        }
    
    # 4. Calendar: Query calendar
    calendar_patterns = [
        r"^ประชุม\s*(.*)$",
        r"^นัดหมาย\s*(.*)$",
        r"^ตารางประชุม\s*(.*)$",
        r"^ตารางวันนี้\s*$",
        r"^ตารางพรุ่งนี้\s*$",
    ]
    for pattern in calendar_patterns:
        match = re.match(pattern, message)
        if match:
            query = match.group(1).strip() if match.group(1) else ""
            logger.info(f"[CommandDetector] Detected: calendar_query, query={query}")
            return {
                "action": "calendar_query",
                "extracted_fields": {"query": query},
                "needs_clarification": False,
                "source": "explicit_command"
            }
    
    # 5. Pantry: List items (including expired)
    pantry_list_patterns = [
        r"^ของในตู้เย็นมีอะไร\s*$",
        r"^ในตู้เย็นมีอะไร\s*$",
        r"^ตู้เย็นมีอะไร\s*$",
        r"^ดูรายการของหมดอายุในตู้เย็น\s*$",
        r"^ดูรายการของในตู้เย็น\s*$",
        r"^ของหมดอายุในตู้เย็น\s*$",
    ]
    for pattern in pantry_list_patterns:
        if re.match(pattern, message):
            logger.info(f"[CommandDetector] Detected: list_pantry")
            return {
                "action": "list_pantry",
                "extracted_fields": {},
                "needs_clarification": False,
                "source": "explicit_command"
            }
    
    # 6. Pantry: Add item
    # Pattern: "ซื้อ<item>" or "เพิ่ม<item>" or "บันทึก<item>" (no space required)
    pantry_add_patterns = [
        (r"^ซื้อ(.+)$", "item"),
        (r"^เพิ่ม(.+)$", "item"),
        (r"^บันทึก(.+)$", "item"),
    ]
    for pattern, key in pantry_add_patterns:
        match = re.match(pattern, message)
        if match:
            item = match.group(1).strip()
            logger.info(f"[CommandDetector] Detected: add_pantry, item={item}")
            return {
                "action": "add_pantry",
                "extracted_fields": {"item_name": item},
                "needs_clarification": False,
                "source": "explicit_command"
            }
    
    # No explicit command matched - return None to use LLM fallback
    logger.info(f"[CommandDetector] No explicit command, fallback to LLM")
    return None


def is_explicit_command(user_message: str) -> bool:
    """Quick check if message matches any explicit command pattern."""
    return detect_command(user_message) is not None
