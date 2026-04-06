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
    "เตือนให้",
    "ปลุก"
]

CANCEL_REMINDER_KEYWORDS = [
    "ยกเลิกนัด",
    "ยกเลิกเตือน",
    "ยกเลิกการแจ้งเตือน",
    "ลบนัด",
    "ลบเตือน",
    "ลบการแจ้งเตือน",
    "ลบรายการที่ต้องทำ",
    "ลบงาน",
    "ลบสิ่งที่ต้องทำ",
    "ยกเลิกนัดหมาย",
    "ยกเลิกแจ้งเตือน",
    "ลบนัดหมาย",
    "ลบแจ้งเตือน",
    "ลบงานที่ต้องทำ"
]

PANTRY_STRONG_KEYWORDS = [
    "ซื้อ",
    "ตู้เย็น",
    "ของหมด",
    "ของในตู้เย็น",
    "วัตถุดิบ",
    "เข้าตู้เย็น",
    "เพิ่มของ",
    "ซื้อเก็บ"
]

# FIX: Use word boundaries to prevent partial matching
# "น\." was matching "วันนี้" - now uses word boundary \b
TIME_INDICATORS = [
    "โมง", "บ่าย", "ทุ่ม", "ตี", r"\bน\.", "เช้า", "เย็น", "ครึ่ง",
    r"\d{1,2}:\d{2}", r"\d{1,2}\s*นาที"
]

# NEW: Agenda/list query patterns - should be checked BEFORE reminder keywords
AGENDA_QUERY_PATTERNS = [
    r"ดูสิ่งที่ต้องทำ",
    r"ดูรายการงาน",
    r"ดูตาราง",
    r"มีอะไรบ้าง",
    r"ต้องทำอะไร",
    r"สรุป.*ประจำวัน",
    r"สรุป.*วันนี้",
    r"สรุป.*เตือน",
    r"สรุปมี.*บ้าง",
    r".*รายการแจ้งเตือน.*บ้าง",
    r"มีงานอะไร",
    r"วันนี้.*ต้องทำ",
    r".*ตั้งเตือน.*บ้าง",
    r"วันนี้.*มี",
    r"พรุ่งนี้.*ต้องทำ",
    r"พรุ่งนี้.*มี",
    r"ฉันต้องทำอะไร",
]

# Connect calendar patterns
CONNECT_CALENDAR_PATTERNS = [
    r"เชื่อมต่อปฏิทิน",
    r"connect.*calendar",
    r"ตั้งค่า.*calendar",
    r"ผูก.*google",
    r"sync.*calendar",
]

# Create calendar event patterns
CREATE_CALENDAR_EVENT_PATTERNS = [
    r"เพิ่มนัดหมาย",
    r"เพิ่มนัด",
    r"จองนัด",
    r"ลงนัด",
    r"นัดหมาย",
    r"มีนัด",
    r"จองตัว",
    r"เพิ่มลงปฏิทิน",
    r"add.*calendar",
    r"create.*event",
]

# List task patterns
LIST_TASKS_PATTERNS = [
    r"^ดูรายการงาน$",
    r"^งานมีอะไรบ้าง$",
    r"^งานที่ต้องทำ$",
    r"^มีงานอะไรบ้าง$",
    r"^ดูงาน$",
]

# ============================================================
# PARKING QUERY DETECTION
# Keyword-based detection for parking location queries
# ============================================================

CAR_KEYWORDS = ["รถ", "จอดรถ"]

# FIXED: Remove standalone "ไหน" which caused false positives
# Only strict location keywords that imply "where is..."
LOCATION_KEYWORDS = [
    "ที่ไหน",
    "อยู่ไหน",
    "ตรงไหน",
    "ชั้นไหน",
    "ชั้นอะไร",
    "โซนไหน",
    "แถวไหน",
    "จุดไหน",
    "บริเวณไหน",
    "ฝั่งไหน"
]

# Negative patterns that should NOT be considered as location queries
INVALID_LOCATION_PATTERNS = [
    "อันไหน",
    "แบบไหน",
    "คันไหน",
    "อะไรดี",
    "อะไรเหมาะ",
    "อันไหนดี",
    "อันไหนถูก"
]

CASUAL_PARTICLES = ["นะ", "ล่ะ", "วะ", "ครับ", "ค่ะ", "พี่", "น้อง", "จ๊ะ"]


def _normalize_parking_query(text: str) -> str:
    """
    Normalize parking query text:
    - lowercase
    - strip spaces
    - remove punctuation (?, !, ., ,)
    - remove trailing casual particles ONLY (not mid-word)
    """
    normalized = text.lower().strip()
    
    for p in ["?", "!", ".", ",", "ๆ", "ฯ"]:
        normalized = normalized.replace(p, "")
    
    for particle in CASUAL_PARTICLES:
        if normalized.endswith(particle):
            normalized = normalized[:-len(particle)].strip()
    
    normalized = re.sub(r"\s+", " ", normalized)
    
    logger.info(f"[ParkingIntent] normalized={normalized}")
    return normalized


def is_parking_query(text: str) -> bool:
    """
    Detect if text is a parking query.
    
    Rules:
    - MUST contain >= 1 CAR_KEYWORD
    - AND >= 1 LOCATION_KEYWORD (from strict list only)
    - MUST NOT contain invalid patterns (อันไหน, แบบไหน, etc.)
    
    Returns True only if all conditions satisfied.
    """
    if not text or len(text.strip()) < 3:
        logger.info(f"[ParkingIntent] final_match=False reason=too_short")
        return False
    
    normalized = _normalize_parking_query(text)
    
    matched_car = [k for k in CAR_KEYWORDS if k in normalized]
    matched_location = [k for k in LOCATION_KEYWORDS if k in normalized]
    
    has_car = len(matched_car) > 0
    has_location = len(matched_location) > 0
    
    invalid_patterns = [p for p in INVALID_LOCATION_PATTERNS if p in normalized]
    has_invalid = len(invalid_patterns) > 0
    
    logger.info(f"[ParkingIntent] raw_input={text[:50]}")
    logger.info(f"[ParkingIntent] normalized={normalized}")
    logger.info(f"[ParkingIntent] matched_car_keywords={matched_car}")
    logger.info(f"[ParkingIntent] matched_location_keywords={matched_location}")
    logger.info(f"[ParkingIntent] invalid_patterns={invalid_patterns}")
    
    if has_invalid:
        logger.info(f"[ParkingIntent] final_match=False reason=invalid_pattern_detected")
        return False
    
    final_match = has_car and has_location
    logger.info(f"[ParkingIntent] final_match={final_match}")
    
    return final_match

# HARDENING: Ambiguous keywords that need clarification when combined with date
AMBIGUOUS_WITH_DATE_KEYWORDS = [
    "ซื้อ",  # "ซื้อไข่พรุ่งนี้" - could be pantry or reminder intent
]


def _has_time_indicator(message: str) -> bool:
    """Check if message contains any time expression."""
    lower_msg = message.lower()
    for indicator in TIME_INDICATORS:
        if re.search(indicator, lower_msg):
            return True
    return False


def _is_ambiguous_intent(message: str) -> bool:
    """Check if message is ambiguous between pantry and reminder."""
    lower_msg = message.lower()
    has_buy = "ซื้อ" in lower_msg
    has_date = any(kw in lower_msg for kw in ["พรุ่งนี้", "วันนี้", "มะรืนนี้", "วันที่", "วันจันทร์", "วันอังคาร", "วันพุธ", "วันพฤหัส", "วันศุกร์", "วันเสาร์", "วันอาทิตย์"])
    return has_buy and has_date


def _get_reminder_keywords_found(message: str) -> list[str]:
    """Return list of matched reminder keywords."""
    lower_msg = message.lower()
    return [kw for kw in REMINDER_FORCE_KEYWORDS if kw in lower_msg]


def _get_pantry_keywords_found(message: str) -> list[str]:
    """Return list of matched pantry keywords."""
    lower_msg = message.lower()
    return [kw for kw in PANTRY_STRONG_KEYWORDS if kw in lower_msg]


def _has_agenda_query_pattern(message: str) -> bool:
    """Check if message matches agenda/list query patterns."""
    lower_msg = message.lower()
    for pattern in AGENDA_QUERY_PATTERNS:
        if re.search(pattern, lower_msg):
            logger.info(f"[IntentV2] matched_query_pattern={pattern}")
            return True
    return False


def _has_list_tasks_pattern(message: str) -> bool:
    """Check if message matches explicit list tasks patterns."""
    lower_msg = message.lower()
    for pattern in LIST_TASKS_PATTERNS:
        if re.match(pattern, lower_msg):
            logger.info(f"[IntentV2] matched_list_tasks_pattern={pattern}")
            return True
    return False


def _classify_intent_with_priority_v2(message: str) -> Optional[Dict[str, Any]]:
    """
    Advanced intent classification with priority layers (Version 2).
    
    Priority (highest → lowest):
    0. Cancel Reminder ("ยกเลิกนัด", "ลบเตือน") — checked FIRST
    1. Agenda/List Query Patterns
    2. Explicit Reminder Signals (FORCE reminder)
    3. Explicit Pantry Signals
    4. Ambiguous Cases
    """
    msg = message.strip()
    lower_msg = msg.lower()
    
    logger.info(f"[IntentV2] raw_input={msg[:50]}")
    
    # Priority -1: Connect Calendar (Meta-command)
    for pattern in CONNECT_CALENDAR_PATTERNS:
        if re.search(pattern, lower_msg):
            logger.info(f"[IntentV2] final_intent=connect_calendar reason=pattern_matched")
            return {
                "action": "connect_calendar",
                "extracted_fields": {},
                "needs_clarification": False,
                "source": "intent_v2"
            }

    # Priority 0: Cancel Reminder — checked BEFORE anything else
    for kw in CANCEL_REMINDER_KEYWORDS:
        if kw in lower_msg:
            # Extract keyword (what to cancel) and optional date
            keyword = re.sub(r'|'.join(re.escape(k) for k in CANCEL_REMINDER_KEYWORDS), '', lower_msg).strip()
            keyword = re.sub(r'\s+(พรุ่งนี้|วันนี้|มะรืนนี้|วันพรุ่งนี้)\s*', ' ', keyword).strip()
            keyword = re.sub(r'ครับ|ค่ะ|นะ|หน่อย|ด้วย', '', keyword).strip()
            
            date_filter = None
            if "พรุ่งนี้" in lower_msg or "วันพรุ่ง" in lower_msg:
                date_filter = "tomorrow"
            elif "วันนี้" in lower_msg:
                date_filter = "today"
            
            logger.info(f"[IntentV2] final_intent=cancel_reminder keyword='{keyword}' date={date_filter}")
            return {
                "action": "cancel_reminder",
                "extracted_fields": {"keyword": keyword, "date_filter": date_filter},
                "needs_clarification": False,
                "source": "intent_v2"
            }
    
    # Priority 1: Agenda/List Query Patterns FIRST
    # Check these BEFORE checking time indicators to avoid false positives

    has_agenda_query = _has_agenda_query_pattern(msg)
    has_list_tasks = _has_list_tasks_pattern(msg)
    
    logger.info(f"[IntentV2] matched_query_patterns={has_agenda_query}")
    logger.info(f"[IntentV2] matched_list_tasks_patterns={has_list_tasks}")
    
    if has_agenda_query:
        target_date = "today"
        if "พรุ่งนี้" in lower_msg or "วันพรุ่ง" in lower_msg:
            target_date = "tomorrow"
        elif "มะรืนนี้" in lower_msg:
            target_date = "day_after_tomorrow"
        else:
            from app.services.reminder_service import reminder_service
            specific_date = reminder_service._parse_specific_date(msg)
            if specific_date:
                target_date = specific_date
                
        logger.info(f"[IntentV2] final_intent=agenda_query reason=query_pattern_matched date={target_date}")
        return {
            "action": "agenda_query",
            "extracted_fields": {"date": target_date},
            "needs_clarification": False,
            "source": "intent_v2"
        }
    
    if has_list_tasks:
        logger.info(f"[IntentV2] final_intent=list_tasks reason=list_tasks_pattern_matched")
        return {
            "action": "list_tasks",
            "extracted_fields": {},
            "needs_clarification": False,
            "source": "intent_v2"
        }
    
    # Priority 2: Parking Query Detection
    if is_parking_query(msg):
        logger.info(f"[IntentV2] final_intent=parking_query reason=keyword_matched")
        return {
            "action": "parking_query",
            "extracted_fields": {},
            "needs_clarification": False,
            "source": "intent_v2"
        }
    
    # New Priority: Create Calendar Event
    # Check this BEFORE generic reminders if it contains calendar keywords
    for pattern in CREATE_CALENDAR_EVENT_PATTERNS:
        if re.search(pattern, lower_msg):
            logger.info(f"[IntentV2] final_intent=create_calendar_event reason=calendar_keyword_found")
            result = _parse_reminder_from_text(msg)
            return {
                "action": "create_calendar_event",
                "extracted_fields": {
                    "message": result.get("message", msg),
                    "date": result.get("date"),
                    "time": result.get("time"),
                    "has_time": result.get("has_time", False),
                    "remind_at": result.get("remind_at"),
                    "validation_error": result.get("validation_error")
                },
                "needs_clarification": result.get("needs_clarification", False),
                "source": "intent_v2"
            }

    # Priority 2: Explicit Reminder Signals
    matched_reminder = _get_reminder_keywords_found(msg)
    has_time = _has_time_indicator(msg)
    
    logger.info(f"[IntentV2] matched_reminder_keywords={matched_reminder}")
    logger.info(f"[IntentV2] has_time_indicator={has_time}")
    
    # NEW rule: Only path to reminder if there is an EXPLICIT reminder keyword.
    # If there's only a time indicator but no reminder keyword, we don't force it here.
    # This allows questions like "Switzerland what time?" to fall through to AI/Chat.
    if matched_reminder:
        # Special case: If has "ซื้อ" + reminder keyword = ambiguous
        if "ซื้อ" in lower_msg:
            logger.warning(f"[IntentV2] clarification_state=ambiguous_buy_with_reminder_keyword")
            return {
                "action": "clarify_intent",
                "extracted_fields": {"message": msg},
                "needs_clarification": True,
                "clarification_question": "ต้องการให้เตือน หรือเพิ่มเข้าตู้เย็นครับ?",
                "source": "intent_v2"
            }
        
        logger.info(f"[IntentV2] final_intent=create_reminder reason=reminder_keyword_found")
        result = _parse_reminder_from_text(msg)
        return {
            "action": "create_reminder",
            "extracted_fields": {
                "message": result.get("message", msg),
                "date": result.get("date"),
                "time": result.get("time"),
                "has_time": result.get("has_time", False),
                "remind_at": result.get("remind_at"),
                "validation_error": result.get("validation_error")
            },
            "needs_clarification": result.get("needs_clarification", False),
            "source": "intent_v2"
        }
    
    # If it has time but NO reminder keyword, we let it fall through 
    # so the AI Classifier (classify_intent) can decide if it's a reminder or just chat.
    if has_time:
        logger.info(f"[IntentV2] has_time=True but no reminder keyword, falling through to AI/Patterns")
    
    # Priority 2: Explicit Pantry Signals (but check ambiguous first)
    # Check ambiguous BEFORE pantry to ensure proper clarification
    if _is_ambiguous_intent(msg):
        logger.warning(f"[IntentV2] clarification_state=ambiguous_buy_with_date")
        logger.info(f"[IntentV2] final_intent=needs_clarification reason=ambiguous_buy_date")
        return {
            "action": "clarify_intent",
            "extracted_fields": {"message": msg},
            "needs_clarification": True,
            "clarification_question": "ต้องการให้เตือน หรือเพิ่มเข้าตู้เย็นครับ?",
            "source": "intent_v2"
        }
    
    # Check pantry keywords AFTER ambiguous check
    matched_pantry = _get_pantry_keywords_found(msg)
    logger.info(f"[IntentV2] matched_pantry_keywords={matched_pantry}")
    
    if matched_pantry:
        logger.info(f"[IntentV2] final_intent=add_pantry reason=pantry_keyword_found")
        item = msg
        for kw in ["ซื้อ", "ตู้เย็น", "ของหมด", "เข้าตู้เย็น", "เพิ่มของ", "ซื้อเก็บ"]:
            item = item.replace(kw, "").strip()
        return {
            "action": "add_pantry",
            "extracted_fields": {"item_name": item or msg},
            "needs_clarification": False,
            "source": "intent_v2"
        }
    
    logger.info(f"[IntentV2] final_intent=None reason=no_priority_match")
    return None


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
    
    # HARDENING: Check for ambiguous intent (e.g., "ซื้อไข่พรุ่งนี้")
    if _is_ambiguous_intent(msg):
        logger.warning(f"[Hardening] clarification_state=ambiguous_intent")
        logger.info(f"[IntentRouting] final_intent=needs_clarification reason=ambiguous_buy_with_date")
        return {
            "action": "clarify_intent",
            "extracted_fields": {"message": msg},
            "needs_clarification": True,
            "clarification_question": "ต้องการเตือนหรือซื้อของครับ?",
            "source": "rule_priority"
        }
    
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
    if parsed.get("date") and parsed.get("time") and not parsed.get("validation_error"):
        remind_at = reminder_service.calculate_remind_at(parsed.get("date"), parsed.get("time"))
    
    needs_clarification = not parsed.get("has_time") or not remind_at or parsed.get("validation_error")
    
    return {
        "message": parsed.get("message", text),
        "date": parsed.get("date"),
        "time": parsed.get("time"),
        "has_time": parsed.get("has_time", False),
        "remind_at": remind_at,
        "needs_clarification": needs_clarification,
        "validation_error": parsed.get("validation_error")
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
    # PART 1: Advanced Intent Disambiguation (V2)
    # Use priority layers to detect intent before explicit patterns
    # ============================================================
    priority_result = _classify_intent_with_priority_v2(message)
    if priority_result:
        logger.info(f"[CommandDetector] IntentV2 matched: {priority_result['action']}")
        return priority_result
    
    # Fallback to original priority rules (for backward compatibility)
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
