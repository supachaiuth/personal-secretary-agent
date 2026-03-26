"""
Reminder service for managing user reminders.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import re
import logging

logger = logging.getLogger(__name__)

INVALID_PREFIX = "[INVALID]"

GARBAGE_PATTERNS = [
    "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า", "สิบ",
    "ครับ", "ค่ะ", "นะ", "ด้วย", "ช่วย", "หน่อย",
    "พรุ่งนี้", "วันพรุ่ง", "มะรืนนี้", "วันนี้", "พรุ่ง",
    "โมง", "บ่าย", "เช้า", "เย็น", "ทุ่ม", "ตี",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
    "๑", "๒", "๓", "๔", "๕", "๖", "๗", "๘", "๙", "๐"
]

MIN_MESSAGE_LENGTH = 3


def is_valid_reminder(reminder_data: Dict[str, Any]) -> bool:
    """
    Validate reminder data before saving or including in summaries.
    
    Rules:
    - message must exist, non-empty, length >= MIN_MESSAGE_LENGTH
    - message must not be a raw dict/object
    - message must not be single word garbage (numbers, pronouns, etc)
    - remind_at must be valid ISO datetime string
    - message must not already be marked invalid
    
    Returns:
        bool: True if valid, False otherwise
    """
    message = reminder_data.get("message")
    remind_at = reminder_data.get("remind_at")
    
    # Check message exists and is string
    if not message or not isinstance(message, str):
        logger.warning(f"[ReminderValidator] Invalid: message is None or not string")
        return False
    
    # Check message not marked as invalid
    if message.startswith(INVALID_PREFIX):
        logger.warning(f"[ReminderValidator] Invalid: message already marked invalid")
        return False
    
    # Check message not raw dict/object
    if message.startswith("{") or message.startswith("["):
        logger.warning(f"[ReminderValidator] Invalid: message appears to be raw object: {message[:50]}")
        return False
    
    # Check message length
    message_clean = message.strip()
    if len(message_clean) < MIN_MESSAGE_LENGTH:
        logger.warning(f"[ReminderValidator] Invalid: message too short ({len(message_clean)} chars): '{message_clean}'")
        return False
    
    # Check message is not single garbage word
    if message_clean in GARBAGE_PATTERNS:
        logger.warning(f"[ReminderValidator] Invalid: message is garbage pattern: '{message_clean}'")
        return False
    
    # Check remind_at exists and valid
    if not remind_at:
        logger.warning(f"[ReminderValidator] Invalid: remind_at is None")
        return False
    
    if not isinstance(remind_at, str) or len(remind_at) < 10:
        logger.warning(f"[ReminderValidator] Invalid: remind_at not valid string: {remind_at}")
        return False
    
    # Try to parse remind_at as ISO datetime
    try:
        datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as e:
        logger.warning(f"[ReminderValidator] Invalid: remind_at not valid ISO format: {remind_at}, error: {e}")
        return False
    
    logger.debug(f"[ReminderValidator] Valid reminder: message='{message_clean[:30]}...', remind_at={remind_at}")
    return True


def mark_reminder_invalid(reminder_data: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    """Mark a reminder as invalid by prefixing the message."""
    result = reminder_data.copy()
    result["message"] = f"{INVALID_PREFIX} {reason} | {result.get('message', '')}"
    return result


class ReminderService:
    """Service for creating and managing reminders."""
    
    def __init__(self):
        pass
    
    def calculate_remind_at(self, date: Optional[str], time: Optional[str]) -> Optional[str]:
        """
        Calculate remind_at ISO string from normalized date and time.
        
        Args:
            date: "today", "tomorrow", "day_after_tomorrow" or None
            time: "HH:MM" format or None
        
        Returns:
            ISO 8601 datetime string in UTC, or None if invalid
        """
        if not date or not time:
            return None
            
        from datetime import datetime, timedelta
        
        now = datetime.utcnow()
        
        # Calculate day offset
        day_offset = 0
        if date == "tomorrow":
            day_offset = 1
        elif date == "day_after_tomorrow":
            day_offset = 2
        
        # Parse time
        hour = 9
        minute = 0
        if time:
            try:
                hour, minute = map(int, time.split(":"))
            except (ValueError, AttributeError):
                return None
        
        # Calculate datetime
        reminder_date = now.date() + timedelta(days=day_offset)
        reminder_datetime = datetime.combine(
            reminder_date,
            datetime.min.time().replace(hour=hour, minute=minute)
        )
        
        # Return UTC ISO format
        return reminder_datetime.isoformat() + "Z"
    
    def parse_reminder_time(self, message: str) -> Optional[datetime]:
        """Parse reminder time from message."""
        message = message.lower().strip()
        
        now = datetime.now()
        
        # Check for "พรุ่งนี้" (tomorrow)
        if "พรุ่งนี้" in message or "วันพรุ่ง" in message:
            day_offset = 1
        # Check for "มะรืนนี้" (day after tomorrow)
        elif "มะรืนนี้" in message:
            day_offset = 2
        # Check for "วันนี้" (today)
        elif "วันนี้" in message:
            day_offset = 0
        else:
            day_offset = 0
        
        # Parse time
        hour = None
        minute = 0
        
        # Pattern: X โมง
        time_match = re.search(r'(\d{1,2})\s*โมง', message)
        if time_match:
            hour = int(time_match.group(1))
        
        # Check for บ่าย (afternoon)
        if "บ่าย" in message:
            if hour is None:
                hour = 13
            else:
                hour += 12
        
        # Check for เช้า (morning)
        if "เช้า" in message and hour is None:
            hour = 8
        
        # Check for เย็น (evening)
        if "เย็น" in message and hour is None:
            hour = 18
        
        # Pattern: HH:MM
        clock_match = re.search(r'(\d{1,2}):(\d{2})', message)
        if clock_match:
            hour = int(clock_match.group(1))
            minute = int(clock_match.group(2))
        
        if hour is None:
            # Default to 9:00 if no time specified
            hour = 9
        
        # Calculate reminder datetime
        reminder_date = now.date() + timedelta(days=day_offset)
        reminder_datetime = datetime.combine(reminder_date, datetime.min.time().replace(hour=hour, minute=minute))
        
        # If time is in the past, move to tomorrow
        if reminder_datetime < now:
            reminder_datetime += timedelta(days=1)
        
        return reminder_datetime
    
    def extract_reminder_message(self, message: str) -> str:
        """Extract the reminder message from user input."""
        parsed = self.parse_reminder_message(message)
        return parsed.get("message", "ไม่ระบุรายละเอียด")
    
    def parse_reminder_message(self, message: str) -> Dict[str, Any]:
        """
        Parse reminder message into components.
        
        Returns:
            dict with keys: message, date, time, has_time
        """
        import logging
        logger = logging.getLogger(__name__)
        
        original_message = message
        message_lower = message.lower().strip()
        
        # Convert Thai numerals to Arabic for time detection and message cleaning
        thai_nums = {
            'หนึ่ง': '1', 'สอง': '2', 'สาม': '3', 'สี่': '4', 'ห้า': '5',
            'หก': '6', 'เจ็ด': '7', 'แปด': '8', 'เก้า': '9', 'สิบ': '10'
        }
        message_for_time = message_lower
        message_for_cleaning = message_lower
        for th, ar in thai_nums.items():
            message_for_time = message_for_time.replace(th, ar)
            message_for_cleaning = message_for_cleaning.replace(th, ar)
        
        logger.info(f"[ReminderService] Parsing: {message_lower}")
        
        # ===== DETECT DATE =====
        date = "today"
        day_offset = 0
        
        if "พรุ่งนี้" in message_lower or "วันพรุ่ง" in message_lower:
            date = "tomorrow"
            day_offset = 1
        elif "มะรืนนี้" in message_lower:
            date = "day_after_tomorrow"
            day_offset = 2
        elif "วันนี้" in message_lower:
            date = "today"
            day_offset = 0
        
        logger.info(f"[ReminderService] Detected date: {date}")
        
        # ===== DETECT TIME - STRICT RULES (ORDER MATTERS!) =====
        # Use message_for_time which has Thai numerals converted to Arabic
        time = None
        hour = None
        minute = 0
        
        # NORMALIZE: Convert 18.00 -> 18:00, 18.00 น -> 18:00, 18.00 น. -> 18:00
        message_normalized = re.sub(r'(\d{1,2})\.(\d{2})\s*น\b', r'\1:\2', message_lower)
        message_normalized = re.sub(r'(\d{1,2})\.(\d{2})\s*น\.', r'\1:\2', message_normalized)
        message_normalized = re.sub(r'(\d{1,2})\.(\d{2})\s*นาที', r'\1:\2', message_normalized)
        message_for_time = re.sub(r'(\d{1,2})\.(\d{2})\s*น\b', r'\1:\2', message_for_time)
        message_for_time = re.sub(r'(\d{1,2})\.(\d{2})\s*น\.', r'\1:\2', message_for_time)
        message_for_time = re.sub(r'(\d{1,2})\.(\d{2})\s*นาที', r'\1:\2', message_for_time)
        
        if message_normalized != message_lower:
            logger.info(f"[ReminderService] Normalized time: {message_lower} -> {message_normalized}")
        
        message_lower = message_normalized
        
        # RULE 1: Check "บ่ายสอง/สาม/สี่/ห้า" FIRST (most specific Thai afternoon times)
        # Use original message_lower for Thai text detection (Thai numerals work better)
        if "บ่ายสอง" in message_lower or "บ่าย 2" in message_lower:
            hour = 14
            time = "14:00"
            logger.info(f"[ReminderService] Detected: บ่ายสอง -> {time}")
        elif "บ่ายสาม" in message_lower or "บ่าย 3" in message_lower:
            hour = 15
            time = "15:00"
            logger.info(f"[ReminderService] Detected: บ่ายสาม -> {time}")
        elif "บ่ายสี่" in message_lower or "บ่าย 4" in message_lower:
            hour = 16
            time = "16:00"
            logger.info(f"[ReminderService] Detected: บ่ายสี่ -> {time}")
        elif "บ่ายห้า" in message_lower or "บ่าย 5" in message_lower:
            hour = 17
            time = "17:00"
        
        # RULE 2: Check compound time words BEFORE simple X โมง
        # Use message_for_time for regex matching (has Arabic numerals)
        if time is None:
            # Check "X โมงเช้า" (e.g., "8 โมงเช้า" = 08:00)
            morning_match = re.search(r'(\d{1,2})\s*โมงเช้า', message_for_time)
            if morning_match:
                hour = int(morning_match.group(1))
                time = f"{hour:02d}:00"
                logger.info(f"[ReminderService] Detected X โมงเช้า: {time}")
            
            # Check "X โมงเย็น" (e.g., "8 โมงเย็น" = 20:00)
            elif re.search(r'(\d{1,2})\s*โมงเย็น', message_for_time):
                hour = 20  # 8 โมงเย็น = 20:00 always
                time = f"{hour:02d}:00"
                logger.info(f"[ReminderService] Detected X โมงเย็น: {time}")
            
            # Check "X ทุ่ม" (Thai evening time: 1 ทุ่ม = 7 PM, 2 ทุ่ม = 8 PM, etc.)
            elif re.search(r'(\d{1,2})\s*ทุ่ม', message_for_time):
                thung_match = re.search(r'(\d{1,2})\s*ทุ่ม', message_for_time)
                thung_hour = int(thung_match.group(1))
                hour = 18 + thung_hour  # 1 ทุ่ม = 19:00, 2 ทุ่ม = 20:00, 3 ทุ่ม = 21:00
                time = f"{hour:02d}:00"
                logger.info(f"[ReminderService] Detected X ทุ่ม: {time}")
            
            # Check "ตีX" (Thai midnight time: ตี1 = 1 AM, ตี2 = 2 AM, etc.)
            # Convert ตีหนึ่ง -> ตี1, ตีสอง -> ตี2
            elif re.search(r'ตี(\d{1,2})', message_for_time):
                tee_match = re.search(r'ตี(\d{1,2})', message_for_time)
                hour = int(tee_match.group(1))
                time = f"{hour:02d}:00"
                logger.info(f"[ReminderService] Detected ตีX: {time}")
        
        # RULE 3: Check simple "X โมง" ONLY if no compound time detected
        if time is None:
            # Match "8 โมง" but NOT if followed by เช้า or เย็น (already handled above)
            time_match = re.search(r'(\d{1,2})\s*โมง(?!เช้า|เย็น)', message_for_time)
            if time_match:
                hour = int(time_match.group(1))
                # If บ่าย is in message (but not บ่ายสอง/สาม/สี่), add 12
                if "บ่าย" in message_lower and hour < 12:
                    hour += 12
                time = f"{hour:02d}:00"
                logger.info(f"[ReminderService] Detected X โมง: {time}")
        
        # RULE 4: Check standalone time words (เช้า, เย็น, ทุ่ม)
        if time is None:
            if "เช้ามาก" in message_lower:
                hour = 7
                time = "07:00"
                logger.info(f"[ReminderService] Detected เช้ามาก -> {time}")
            elif "เช้า" in message_lower:
                hour = 8
                time = "08:00"
                logger.info(f"[ReminderService] Detected เช้า -> {time}")
            elif "เย็น" in message_lower:
                hour = 18
                time = "18:00"
                logger.info(f"[ReminderService] Detected เย็น -> {time}")
            elif "ทุ่ม" in message_lower:
                hour = 19
                time = "19:00"
                logger.info(f"[ReminderService] Detected ทุ่ม -> {time}")
        
        # RULE 5: Check HH:MM pattern
        if time is None:
            clock_match = re.search(r'(\d{1,2}):(\d{2})', message_lower)
            if clock_match:
                hour = int(clock_match.group(1))
                minute = int(clock_match.group(2))
                time = f"{hour:02d}:{minute:02d}"
                logger.info(f"[ReminderService] Detected HH:MM -> {time}")
        
        # RULE 6: Check Thai minute patterns like "9 โมง 5 นาที" or "9 โมง 30 นาที"
        if time is not None and minute == 0:
            minute_match = re.search(r'(\d{1,2})\s*นาที', message_for_time)
            if minute_match:
                minute = int(minute_match.group(1))
                time = f"{hour:02d}:{minute:02d}"
                logger.info(f"[ReminderService] Detected X นาที -> {time}")
        
        has_time = time is not None
        logger.info(f"[ReminderService] Final time: {time}, has_time={has_time}, hour={hour}")
        
        # ===== CLEAN MESSAGE =====
        original_message_for_debug = message_lower
        cleaned = message_lower
        
        logger.info(f"[ReminderService] Clean: original='{original_message_for_debug}'")
        
        # FIRST: Remove reminder command words (before anything else)
        cleaned = re.sub(r'^ช่วย\s+', '', cleaned)
        cleaned = re.sub(r'^(เตือน|แจ้งเตือน)\s*', '', cleaned)
        cleaned = re.sub(r'\s+(เตือน|แจ้งเตือน)\s+', ' ', cleaned)
        cleaned = re.sub(r'^(อย่าลืม)\s*', '', cleaned)
        
        cleaned = re.sub(r'^(หน่อย|นะ|ครับ|ค่ะ|ด้วย)\s*', '', cleaned)
        
        detected_date_phrase = None
        date_patterns = [
            (r'วันพรุ่งนี้', 'วันพรุ่งนี้'),
            (r'พรุ่งนี้', 'พรุ่งนี้'),
            (r'มะรืนนี้', 'มะรืนนี้'),
            (r'วันนี้', 'วันนี้'),
            (r'พรุ่ง(?=\s|$)', 'พรุ่ง'),
            (r'วันพรุ่ง(?=\s|$)', 'วันพรุ่ง'),
        ]
        for pattern, phrase in date_patterns:
            if re.search(pattern, cleaned):
                detected_date_phrase = phrase
                cleaned = re.sub(pattern, ' ', cleaned)
                logger.info(f"[ReminderService] Clean: removed date phrase '{phrase}'")
                break
        
        detected_time_phrase = None
        time_patterns = [
            (r'บ่ายสอง', 'บ่ายสอง'),
            (r'บ่าย\s*2', 'บ่าย 2'),
            (r'บ่ายสาม', 'บ่ายสาม'),
            (r'บ่าย\s*3', 'บ่าย 3'),
            (r'บ่ายสี่', 'บ่ายสี่'),
            (r'บ่าย\s*4', 'บ่าย 4'),
            (r'บ่ายห้า', 'บ่ายห้า'),
            (r'บ่าย\s*5', 'บ่าย 5'),
            (r'\d{1,2}\s*โมงเช้า', None),
            (r'\d{1,2}\s*โมงเย็น', None),
            (r'\d{1,2}\s*โมง', None),
            (r'\d{1,2}\s*ทุ่ม', None),
            (r'ตี\d{1,2}', None),
            (r'\d{1,2}\s*นาที', None),
        ]
        
        for pattern, _ in time_patterns:
            match = re.search(pattern, cleaned)
            if match:
                detected_time_phrase = match.group(0)
                cleaned = re.sub(pattern, ' ', cleaned, count=1)
                logger.info(f"[ReminderService] Clean: removed time phrase '{detected_time_phrase}'")
                break
        
        cleaned = re.sub(r'ตอน\s*\d+', ' ', cleaned)
        cleaned = re.sub(r'เวลา\s*\d+', ' ', cleaned)
        cleaned = re.sub(r'\d{1,2}:\d{2}', ' ', cleaned)
        
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        logger.info(f"[ReminderService] Clean: before_fallback='{cleaned}'")
        
        is_low_quality = (
            not cleaned or
            len(cleaned) < 3 or
            cleaned in ['นะ', 'ครับ', 'ค่ะ', 'ด้วย', 'หน่อย', 'ที', 'ตอน', 'เวลา', 'ให้']
        )
        
        fallback_triggered = False
        if is_low_quality:
            fallback_triggered = True
            cleaned = original_message
            cleaned = re.sub(r'^(ช่วย|เตือน|แจ้งเตือน|อย่าลืม)\s*', '', cleaned)
            cleaned = re.sub(r'\s+(พรุ่งนี้|วันนี้|มะรืนนี้|วันพรุ่งนี้)\s+', ' ', cleaned)
            cleaned = re.sub(r'\d{1,2}\s*โมง.*$', '', cleaned)
            cleaned = re.sub(r'\d{1,2}:\d{2}.*$', '', cleaned)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            logger.info(f"[ReminderService] Clean: fallback triggered, safe_text='{cleaned}'")
        
        cleaned_final = cleaned
        
        logger.info(f"[ReminderService] Clean: after_normalize='{cleaned_final}', date_phrase='{detected_date_phrase}', time_phrase='{detected_time_phrase}', fallback={fallback_triggered}")
        
        # ===== CALCULATE REMIND_AT =====
        # CRITICAL: User says "8 โมง" which is Bangkok time (UTC+7)
        # We need to convert Bangkok time to UTC before storing
        remind_at = None
        if has_time and hour is not None:
            from datetime import datetime, timedelta, timezone
            now = datetime.utcnow()
            reminder_date = now.date() + timedelta(days=day_offset)
            
            # Create datetime as Bangkok time first
            bangkok_offset = timedelta(hours=7)
            bangkok_tz = timezone(bangkok_offset)
            reminder_datetime_bangkok = datetime.combine(
                reminder_date,
                datetime.min.time().replace(hour=hour, minute=minute),
                tzinfo=bangkok_tz
            )
            
            # Convert to UTC for storage
            reminder_datetime_utc = reminder_datetime_bangkok.astimezone(timezone.utc)
            remind_at = reminder_datetime_utc.isoformat().replace("+00:00", "Z")
            
            logger.info(f"[ReminderService] Bangkok: {reminder_datetime_bangkok} -> UTC: {remind_at}")
        
        return {
            "message": cleaned_final if cleaned_final else original_message,
            "date": date,
            "time": time,
            "has_time": has_time,
            "remind_at": remind_at
        }
    
    def create_reminder(
        self,
        user_id: str,
        message: str,
        remind_at: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Create a reminder for the user. Returns None if validation fails."""
        if remind_at is None:
            remind_at = self.parse_reminder_time(message)
        
        if remind_at is None:
            logger.warning(f"[ReminderService] Cannot parse reminder time from: {message}")
            return None
        
        parsed = self.parse_reminder_message(message)
        reminder_message = parsed.get("message", "")
        
        reminder_data = {
            "user_id": user_id,
            "message": reminder_message,
            "remind_at": remind_at.isoformat() if isinstance(remind_at, datetime) else remind_at,
            "status": "pending"
        }
        
        if not is_valid_reminder(reminder_data):
            logger.warning(f"[ReminderService] Reminder validation failed for: {message}")
            return None
        
        return reminder_data
    
    def format_reminder_response(self, reminder: Dict[str, Any]) -> str:
        """Format reminder as response string."""
        remind_at = reminder.get("remind_at", "")
        message = reminder.get("message", "ไม่ระบุ")
        
        try:
            dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
            bangkok_time = dt.astimezone() if dt.tzinfo else dt
            formatted_date = bangkok_time.strftime("วันที่ %d/%m/%Y เวลา %H:%M น.")
        except Exception:
            formatted_date = remind_at
        
        return f"✅ เตือน '{message}' ไว้เมื่อ {formatted_date} ครับ!"
    
    def normalize_reminder_display(self, parsed: Dict[str, Any]) -> str:
        """
        Generate normalized user-facing display text for a reminder.
        
        Format: "HH:MM ความหมาย" or fallback to cleaned message if no time.
        """
        time_val = parsed.get("time")
        raw_message = parsed.get("message", "")
        original = parsed.get("_original", "")
        
        logger.info(f"[ReminderService] Normalize: time={time_val}, raw_message='{raw_message}'")
        
        if time_val:
            try:
                hour, minute = map(int, time_val.split(":"))
                time_prefix = f"{hour:02d}:{minute:02d}"
            except (ValueError, AttributeError):
                time_prefix = time_val
        else:
            time_prefix = None
        
        action_text = raw_message.strip()
        forbidden_actions = ['นะ', 'ครับ', 'ค่ะ', 'ด้วย', 'หน่อย', 'ที', 'ตอน', 'เวลา', 'ให้', 'นี้', 'ฉัน', '']
        
        if action_text in forbidden_actions or len(action_text) < 2:
            action_text = self._extract_fallback_action(original, time_prefix is not None)
            logger.info(f"[ReminderService] Normalize: used fallback action='{action_text}'")
        
        if time_prefix:
            normalized = f"{time_prefix} {action_text}"
            logger.info(f"[ReminderService] Normalize: result='{normalized}'")
            return normalized
        
        return action_text
    
    def _extract_fallback_action(self, original: str, has_time: bool) -> str:
        """Extract cleaner action text as fallback."""
        if not original:
            return "เตือน"
        
        cleaned = original.lower()
        
        prefixes = ['ช่วย', 'เตือน', 'แจ้งเตือน', 'อย่าลืม', 'ปลุก']
        for prefix in prefixes:
            if cleaned.startswith(prefix):
                result = original[len(prefix):].strip()
                if result and len(result) > 1:
                    return result
        
        if has_time:
            time_patterns = [
                r'(\d{1,2})\s*โมงเย็น',
                r'(\d{1,2})\s*โมงเช้า',
                r'(\d{1,2})\s*โมง',
                r'(\d{1,2}):(\d{2})',
                r'ตอน\s*(\d{1,2})',
            ]
            for pattern in time_patterns:
                match = re.search(pattern, cleaned)
                if match:
                    end_pos = match.end()
                    if end_pos < len(original):
                        result = original[end_pos:].strip()
                        if result:
                            return result
        
        return original[:50] if len(original) > 50 else original
    
    def format_reminder_list(self, reminders: List[Dict[str, Any]], title: str = "รายการเตือน") -> str:
        """
        Format a list of reminders with proper time sorting.
        
        - Timed items sorted by time ascending
        - Untimed items in separate section
        """
        if not reminders:
            return f"{title}:\n  ไม่มีรายการ"
        
        timed = []
        untimed = []
        
        for rem in reminders:
            remind_at = rem.get("remind_at", "")
            message = rem.get("message", "")
            
            if remind_at:
                try:
                    dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
                    bangkok = dt.astimezone() if dt.tzinfo else dt
                    minutes = bangkok.hour * 60 + bangkok.minute
                    timed.append({
                        "minutes": minutes,
                        "time_str": bangkok.strftime("%H:%M"),
                        "message": message,
                        "remind_at": remind_at
                    })
                except Exception:
                    untimed.append({"message": message, "remind_at": remind_at})
            else:
                untimed.append({"message": message, "remind_at": remind_at})
        
        timed.sort(key=lambda x: x["minutes"])
        
        logger.info(f"[ReminderService] List: timed_count={len(timed)}, untimed_count={len(untimed)}")
        
        lines = [title]
        
        for item in timed:
            lines.append(f"  • {item['time_str']} {item['message']}")
        
        if untimed:
            lines.append("")
            lines.append("📝 อื่นๆ:")
            for item in untimed:
                lines.append(f"  • {item['message']}")
        
        return "\n".join(lines)


reminder_service = ReminderService()
