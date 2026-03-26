"""
Command detector with hard rules BEFORE LLM classification.
Implements deterministic behavior for common commands.
"""
import re
import logging
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# ============================================================
# PART 1: REMINDER → PANTRY MISROUTING FIX
# Strong intent priority rule: reminder keywords FORCE create_reminder
# ============================================================

REMINDER_FORCE_KEYWORDS = [
    "เตือน",
    "แจ้งเตือน",
    "อย่าลืม",
    "เตือนฉัน",
    "ช่วยเตือน",
    "เตือนให้"
]

PANTRY_STRONG_KEYWORDS = [
    "ซื้อ",
    "ตู้เย็น",
    "ของหมด",
    "ของในตู้เย็น",
    "วัตถุดิบ"
]


def _get_reminder_keywords_found(message: str) -> list[str]:
    """Return list of matched reminder keywords."""
    lower_msg = message.lower()
    return [kw for kw in REMINDER_FORCE_KEYWORDS if kw in lower_msg]


def _get_pantry_keywords_found(message: str) -> list[str]:
    """Return list of matched pantry keywords."""
    lower_msg = message.lower()
    return [kw for kw in PANTRY_STRONG_KEYWORDS if kw in lower_msg]


def _classify_intent_with_priority_rules(message: str) -> Optional[Dict[str, Any]]:
    """
    Rule-based intent classification BEFORE AI fallback.
    
    Priority:
    1. If ANY reminder keyword found → FORCE create_reminder
    2. If pantry keyword found AND no reminder keyword → add_pantry
    3. Otherwise → continue to normal detection
    """
    msg = message.strip()
    lower_msg = msg.lower()
    
    matched_reminder = _get_reminder_keywords_found(msg)
    matched_pantry = _get_pantry_keywords_found(msg)
    
    logger.info(f"[IntentRouting] raw_input={msg[:50]}")
    logger.info(f"[IntentRouting] matched_reminder_keywords={matched_reminder}")
    logger.info(f"[IntentRouting] matched_pantry_keywords={matched_pantry}")
    
    if matched_reminder:
        logger.info(f"[IntentRouting] final_intent=create_reminder reason=reminder_keyword_found")
        result = _parse_reminder_from_text(msg)
        return {
            "action": "create_reminder",
            "extracted_fields": {
                "message": result.get("message", msg),
                "date": result.get("date"),
                "time": result.get("time"),
                "has_time": result.get("has_time", False),
                "remind_at": result.get("remind_at")
            },
            "needs_clarification": result.get("needs_clarification", False),
            "source": "rule_priority"
        }
    
    if matched_pantry and not matched_reminder:
        logger.info(f"[IntentRouting] final_intent=add_pantry reason=pantry_keyword_no_reminder")
        item = msg.replace("ซื้อ", "").replace("ตู้เย็น", "").replace("ของหมด", "").strip()
        return {
            "action": "add_pantry",
            "extracted_fields": {"item_name": item or msg},
            "needs_clarification": False,
            "source": "rule_priority"
        }
    
    logger.info(f"[IntentRouting] final_intent=None reason=fallthrough_to_normal_detection")
    return None


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


def _parse_reminder_from_text(text: str) -> Dict[str, Any]:
    """Parse reminder from free-form Thai text."""
    from app.services.reminder_service import reminder_service
    
    parsed = reminder_service.parse_reminder_message(text)
    
    remind_at = None
    if parsed.get("date") and parsed.get("time"):
        remind_at = reminder_service.calculate_remind_at(parsed.get("date"), parsed.get("time"))
    
    needs_clarification = not parsed.get("has_time") or not remind_at
    
    return {
        "message": parsed.get("message", text),
        "date": parsed.get("date"),
        "time": parsed.get("time"),
        "has_time": parsed.get("has_time", False),
        "remind_at": remind_at,
        "needs_clarification": needs_clarification
    }


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
    
    # ============================================================
    # PART 1 FIX: Rule-based priority BEFORE explicit patterns
    # Check for reminder keywords FIRST to prevent pantry misrouting
    # ============================================================
    priority_result = _classify_intent_with_priority_rules(message)
    if priority_result:
        logger.info(f"[CommandDetector] Rule priority matched: {priority_result['action']}")
        return priority_result
    
    # 1. Task: Add new task
    # Pattern: "เพิ่มงาน<text>" or "เพิ่มงาน <text>" (space optional)
    match = re.match(r"^เพิ่มงาน(.+)$", message)
    if match:
        title = match.group(1).strip()
        logger.info(f"[CommandDetector] Detected: add_task, title={title}")
        return {
            "action": "add_task",
            "extracted_fields": {"title": title},
            "needs_clarification": False,
            "source": "explicit_command"
        }
    
    # Pattern: "เพิ่ม <text>" (without "งาน") - but NOT pantry items
    # Must NOT match patterns like "เพิ่มผัก" (pantry), "เพิ่มหมู" (pantry)
    # Only match if it looks like a task (contains งาน, task keywords, or is longer)
    match = re.match(r"^เพิ่ม\s+([^\s].+)$", message)
    if match:
        title = match.group(1).strip()
        # Additional check: if it looks like pantry item, skip
        pantry_keywords = ['ผัก', 'หมู', 'ไก่', 'ปลา', 'ข้าว', 'น้ำ', 'ไข่', 'นม', 'ผลไม้', 'ส้ม', 'กล้วย', 'มะม่วง', 'อาหาร', 'วัตถุดิบ']
        is_likely_pantry = any(pk in title for pk in pantry_keywords)
        
        if not is_likely_pantry:
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
    
    # 2b. Agenda/Tomorrow queries - must check BEFORE reminder
    if message.startswith("พรุ่งนี้") or message.startswith("วันพรุ่งนี้"):
        date_val = "tomorrow"
        if message.startswith("พรุ่งนี้"):
            date_val = "tomorrow"
        elif message.startswith("วันพรุ่งนี้"):
            date_val = "tomorrow"
        
        if "วันนี้" in message:
            date_val = "today"
        
        logger.info(f"[CommandDetector] Detected: agenda_query, date={date_val}")
        return {
            "action": "agenda_query",
            "extracted_fields": {"date": date_val},
            "needs_clarification": False,
            "source": "explicit_command"
        }
    
    if re.match(r"^วันนี้.*(ต้องทำ|มี)", message):
        logger.info(f"[CommandDetector] Detected: agenda_query, date=today")
        return {
            "action": "agenda_query",
            "extracted_fields": {"date": "today"},
            "needs_clarification": False,
            "source": "explicit_command"
        }
    
    # 3. Reminder: Create reminder (at beginning)
    # Pattern: "เตือน <message>" or "เตือนฉัน <message>" or "แจ้งเตือน <message>"
    reminder_match = re.match(r"^(เตือน|แจ้งเตือน)\s*(.*)$", message)
    if reminder_match:
        raw_text = reminder_match.group(2).strip()
        logger.info(f"[CommandDetector] Detected: create_reminder, raw={raw_text}")
        
        result = _parse_reminder_from_text(raw_text)
        
        logger.info(f"[CommandDetector] Reminder parsed: {result}")
        
        return {
            "action": "create_reminder",
            "extracted_fields": {
                "message": result.get("message", raw_text),
                "date": result.get("date"),
                "time": result.get("time"),
                "has_time": result.get("has_time", False),
                "remind_at": result.get("remind_at")
            },
            "needs_clarification": result.get("needs_clarification", False),
            "source": "explicit_command"
        }
    
    # 3b. Reminder: Free-form with reminder keywords anywhere
    # Patterns like: "พรุ่งนี้ 8 โมง เตือนผมหน่อย มีประชุม"
    # Or: "ช่วยเตือนด้วยนะ พรุ่งนี้ 9 โมง"
    reminder_keywords = ["เตือน", "แจ้งเตือน", "ช่วยเตือน", "เตือนด้วย", "อย่าลืม"]
    if any(kw in lower_message for kw in reminder_keywords):
        logger.info(f"[CommandDetector] Detected reminder keyword in: {message}")
        
        result = _parse_reminder_from_text(message)
        
        if result.get("has_time") and result.get("remind_at"):
            logger.info(f"[CommandDetector] Free-form reminder parsed: {result}")
            return {
                "action": "create_reminder",
                "extracted_fields": {
                    "message": result.get("message", message),
                    "date": result.get("date"),
                    "time": result.get("time"),
                    "has_time": result.get("has_time", False),
                    "remind_at": result.get("remind_at")
                },
                "needs_clarification": False,
                "source": "explicit_command"
            }
        else:
            logger.info(f"[CommandDetector] Free-form reminder needs clarification")
    
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
    # ONLY match if it looks like a food/pantry item
    # PART 1 FIX: Skip pantry detection if reminder keywords present
    pantry_keywords = ['ผัก', 'หมู', 'ไก่', 'ปลา', 'กุ้ง', 'ข้าว', 'น้ำ', 'ไข่', 'นม', 'ผลไม้', 'ส้ม', 'กล้วย', 'มะม่วง', 'อาหาร', 'วัตถุดิบ', 'ของ', 'กิน', 'ในตู้', 'ในครัว', 'ตู้เย็น', 'ครัว']
    
    # Guard: Don't route to pantry if reminder keyword present
    if _get_reminder_keywords_found(message):
        logger.info(f"[CommandDetector] Skipping pantry detection: reminder keyword present")
    else:
        pantry_add_patterns = [
            (r"^ซื้อ(.+)$", "item"),
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
    
    # Special case: "เพิ่ม" for pantry - only if followed by food keyword
    match = re.match(r"^เพิ่ม(.+)$", message)
    if match:
        item = match.group(1).strip()
        if any(pk in item for pk in pantry_keywords):
            logger.info(f"[CommandDetector] Detected: add_pantry (เพิ่ม+food), item={item}")
            return {
                "action": "add_pantry",
                "extracted_fields": {"item_name": item},
                "needs_clarification": False,
                "source": "explicit_command"
            }
    
    # No explicit command matched - try AI classification
    logger.info(f"[CommandDetector] No explicit command, trying AI classification")
    
    try:
        from app.services.intent_classifier import classify_intent, extract_fields_for_intent
        
        intent = classify_intent(message)
        logger.info(f"[CommandDetector] AI classified: {intent}")
        
        if intent and intent != "chat":
            fields = extract_fields_for_intent(message, intent)
            
            needs_clarification = False
            if intent == "create_reminder" and not fields.get("has_time"):
                needs_clarification = True
            
            return {
                "action": intent,
                "extracted_fields": fields,
                "needs_clarification": needs_clarification,
                "source": "ai_classification"
            }
    except Exception as e:
        logger.error(f"[CommandDetector] AI classification failed: {e}")
    
    # Fallback to LLM chat
    return None


def is_explicit_command(user_message: str) -> bool:
    """Quick check if message matches any explicit command pattern."""
    return detect_command(user_message) is not None
