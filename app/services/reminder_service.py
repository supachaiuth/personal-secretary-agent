"""
Reminder service for managing user reminders.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
import logging

logger = logging.getLogger(__name__)

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")

# Month name mappings for specific date parsing (Thai + English)
MONTH_NAMES = {
    "มกราคม": 1, "มกรา": 1, "ม.ค.": 1,
    "กุมภาพันธ์": 2, "กุมภา": 2, "ก.พ.": 2,
    "มีนาคม": 3, "มีนา": 3, "มี.ค.": 3,
    "เมษายน": 4, "เมษา": 4, "เม.ย.": 4,
    "พฤษภาคม": 5, "พฤษภา": 5, "พ.ค.": 5,
    "มิถุนายน": 6, "มิถุนา": 6, "มิ.ย.": 6,
    "กรกฎาคม": 7, "กรกฎา": 7, "ก.ค.": 7,
    "สิงหาคม": 8, "สิงหา": 8, "ส.ค.": 8,
    "กันยายน": 9, "กันยา": 9, "ก.ย.": 9,
    "ตุลาคม": 10, "ตุลา": 10, "ต.ค.": 10,
    "พฤศจิกายน": 11, "พฤศจิกา": 11, "พ.ย.": 11,
    "ธันวาคม": 12, "ธันวา": 12, "ธ.ค.": 12,
    "january": 1, "jan": 1, "february": 2, "feb": 2,
    "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

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
            
        from datetime import datetime, timedelta, timezone
        
        # FIX: Use Bangkok local time (UTC+7) to calculate day offset
        bangkok_offset = timedelta(hours=7)
        bangkok_tz = timezone(bangkok_offset)
        now_bangkok = datetime.now(bangkok_tz)
        
        logger.info(f"[ReminderService] calculate_remind_at: now_bangkok={now_bangkok.isoformat()}")
        
        # Parse time
        hour = 9
        minute = 0
        if time:
            try:
                hour, minute = map(int, time.split(":"))
            except (ValueError, AttributeError):
                return None
        
        # Calculate reminder date — relative OR absolute ("YYYY-MM-DD")
        if date in ("today", "tomorrow", "day_after_tomorrow", None):
            day_offset = 0
            if date == "tomorrow":
                day_offset = 1
            elif date == "day_after_tomorrow":
                day_offset = 2
            reminder_date_bangkok = now_bangkok.date() + timedelta(days=day_offset)
        else:
            # Absolute date string "YYYY-MM-DD"
            try:
                from datetime import date as date_type
                reminder_date_bangkok = date_type.fromisoformat(date)
            except (ValueError, AttributeError):
                logger.warning(f"[ReminderService] Invalid absolute date: {date}")
                return None
        
        reminder_datetime_bangkok = datetime.combine(
            reminder_date_bangkok,
            datetime.min.time().replace(hour=hour, minute=minute),
            tzinfo=bangkok_tz
        )
        
        # Convert to UTC for storage
        reminder_datetime_utc = reminder_datetime_bangkok.astimezone(timezone.utc)
        
        logger.info(f"[ReminderService] calculate_remind_at: {date} + {time} = Bangkok {reminder_datetime_bangkok.isoformat()} -> UTC {reminder_datetime_utc.isoformat()}")
        
        # Return UTC ISO format
        return reminder_datetime_utc.isoformat().replace("+00:00", "Z")
    
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
        else:
            # Try specific date parsing ("5 เมษา", "1 Apr", "Apr 5", "วันที่ 5 เม.ย.")
            specific = self._parse_specific_date(original_message)
            if specific:
                date = specific  # "YYYY-MM-DD" absolute string
                day_offset = None  # not used for absolute dates
        
        logger.info(f"[ReminderService] Detected date: {date}")
        
        # ===== DETECT TIME - STRICT RULES (ORDER MATTERS!) =====
        # Use message_for_time which has Thai numerals converted to Arabic
        time = None
        hour = None
        minute = 0
        
        # NORMALIZE: Convert decimal time formats FIRST (before other patterns)
        # Handles: "6.00 โมง" -> "6:00", "11.15 โมง" -> "11:15", "7.30" -> "7:30"
        decimal_pattern = r'(\d{1,2})\.(\d{2})(?:\s*โมง|\s*น\.?|\s*นาที)?'
        message_normalized = re.sub(decimal_pattern, r'\1:\2', message_lower)
        message_for_time = re.sub(decimal_pattern, r'\1:\2', message_for_time)
        
        if message_normalized != message_lower:
            logger.info(f"[TimeParser] raw_input={message_lower}")
            logger.info(f"[TimeParser] matched_decimal_time={message_normalized}")
        
        message_lower = message_normalized
        
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
            
            # Check "X โมงเย็น" (e.g., "6 โมงเย็น" = 18:00, "7 โมงเย็น" = 19:00)
            yen_match = re.search(r'(\d{1,2})\s*โมงเย็น', message_for_time)
            if time is None and yen_match:
                yen_hour = int(yen_match.group(1))
                hour = yen_hour + 12  # 6 โมงเย็น = 18:00, 7 โมงเย็น = 19:00, etc.
                time = f"{hour:02d}:00"
                logger.info(f"[ReminderService] Detected X โมงเย็น: {time}")
            
            # Check "X ทุ่ม" (Thai evening time: 1 ทุ่ม = 7 PM, 2 ทุ่ม = 8 PM, etc.)
            thung_match = re.search(r'(\d{1,2})\s*ทุ่ม', message_for_time)
            if time is None and thung_match:
                thung_hour = int(thung_match.group(1))
                hour = 18 + thung_hour  # 1 ทุ่ม = 19:00, 2 ทุ่ม = 20:00, 3 ทุ่ม = 21:00
                time = f"{hour:02d}:00"
                logger.info(f"[ReminderService] Detected X ทุ่ม: {time}")
            
            # Check "ตีX" (Thai midnight time: ตี1 = 1 AM, ตี2 = 2 AM, etc.)
            tee_match = re.search(r'ตี(\d{1,2})', message_for_time)
            if time is None and tee_match:
                hour = int(tee_match.group(1))
                # Validate: hour must be 0-23
                if hour > 23:
                    is_valid_time = False
                    invalid_reason = f"hour_out_of_range_{hour}"
                    logger.warning(f"[TimeParserV2] Invalid hour: {hour} > 23")
                    logger.warning(f"[TimeParserV2] validation_error={invalid_reason}")
                else:
                    time = f"{hour:02d}:00"
                    logger.info(f"[TimeParserV2] raw_input={message_lower}")
                    logger.info(f"[TimeParserV2] parsed_time={time}")
                    logger.info(f"[ReminderService] Detected ตีX: {time}")
        
        # RULE 3: Check simple "X โมง" ONLY if no compound time detected
        if time is None:
            # Check "X โมงครึ่ง" (e.g., "8 โมงครึ่ง" = 08:30) BEFORE simple "X โมง"
            half_match = re.search(r'(\d{1,2})\s*โมง\s*ครึ่ง', message_for_time)
            if half_match:
                hour = int(half_match.group(1))
                minute = 30
                time = f"{hour:02d}:30"
                logger.info(f"[TimeParserV2] raw_input={message_lower}")
                logger.info(f"[TimeParserV2] parsed_time={time}")
                logger.info(f"[ReminderService] Detected X โมงครึ่ง -> {time}")
            
            # Match "8 โมง" but NOT if followed by เช้า or เย็น or ครึ่ง (already handled above)
            elif re.search(r'(\d{1,2})\s*โมง(?!เช้า|เย็น|ครึ่ง)', message_for_time):
                time_match = re.search(r'(\d{1,2})\s*โมง(?!เช้า|เย็น|ครึ่ง)', message_for_time)
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
                # Validate: hour 0-23, minute 0-59
                if hour > 23:
                    is_valid_time = False
                    invalid_reason = f"hour_out_of_range_{hour}"
                    logger.warning(f"[TimeParserV2] Invalid hour: {hour} > 23")
                    logger.warning(f"[TimeParserV2] validation_error={invalid_reason}")
                elif minute >= 60:
                    is_valid_time = False
                    invalid_reason = f"minute_out_of_range_{minute}"
                    logger.warning(f"[TimeParserV2] Invalid minute: {minute} >= 60")
                    logger.warning(f"[TimeParserV2] validation_error={invalid_reason}")
                else:
                    time = f"{hour:02d}:{minute:02d}"
                    logger.info(f"[TimeParserV2] raw_input={message_lower}")
                    logger.info(f"[TimeParserV2] parsed_time={time}")
                    logger.info(f"[ReminderService] Detected HH:MM -> {time}")
        
        # RULE 6: Check Thai minute patterns like "9 โมง 5 นาที" or "9 โมง 30 นาที"
        # PART 2: Enhanced minute parsing with validation
        if time is not None and minute == 0:
            # Check "X โมง Y นาที" pattern first
            minute_compound_match = re.search(r'(\d{1,2})\s*โมง\s*(\d{1,2})\s*นาที', message_for_time)
            if minute_compound_match:
                parsed_minute = int(minute_compound_match.group(2))
                # Validate: minute must be 0-59
                if parsed_minute >= 60:
                    is_valid_time = False
                    invalid_reason = f"minute_out_of_range_{parsed_minute}"
                    logger.warning(f"[TimeParserV2] Invalid minute: {parsed_minute} >= 60")
                    logger.warning(f"[TimeParserV2] validation_error={invalid_reason}")
                else:
                    minute = parsed_minute
                    time = f"{hour:02d}:{minute:02d}"
                    logger.info(f"[TimeParserV2] raw_input={message_lower}")
                    logger.info(f"[TimeParserV2] parsed_time={time}")
                    logger.info(f"[ReminderService] Detected X โมง Y นาที -> {time}")
            else:
                # Simple "X นาที" pattern
                minute_match = re.search(r'(\d{1,2})\s*นาที', message_for_time)
                if minute_match:
                    minute = int(minute_match.group(1))
                    # Validate: minute must be 0-59
                    if minute >= 60:
                        is_valid_time = False
                        invalid_reason = f"minute_out_of_range_{minute}"
                        logger.warning(f"[TimeParserV2] Invalid minute: {minute} >= 60")
                        logger.warning(f"[TimeParserV2] validation_error={invalid_reason}")
                    else:
                        time = f"{hour:02d}:{minute:02d}"
                        logger.info(f"[TimeParserV2] raw_input={message_lower}")
                        logger.info(f"[TimeParserV2] parsed_time={time}")
                        logger.info(f"[ReminderService] Detected X นาที -> {time}")
        
        has_time = time is not None
        
        # HARDENING: Validate parsed time values
        is_valid_time = True
        invalid_reason = None
        
        if hour is not None:
            if hour > 23:
                is_valid_time = False
                invalid_reason = f"hour_out_of_range_{hour}"
                logger.warning(f"[Hardening] Invalid time: hour={hour} > 23")
            if minute >= 60:
                is_valid_time = False
                invalid_reason = f"minute_out_of_range_{minute}"
                logger.warning(f"[Hardening] Invalid time: minute={minute} >= 60")
        
        has_time = time is not None
        
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
            cleaned = re.sub(r'\s+(พรุ่งนี้|วันนี้|มะรืนนี้|วันพรุ่งนี้)\s*', ' ', cleaned)
            cleaned = re.sub(r'\d{1,2}\s*โมง.*$', '', cleaned)
            cleaned = re.sub(r'\d{1,2}:\d{2}.*$', '', cleaned)
            cleaned = re.sub(r'\d{1,2}\.\d{2}.*$', '', cleaned)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            # If after aggressive fallback cleanup, it is still low quality, just admit it's empty
            if not cleaned or cleaned in ['นะ', 'ครับ', 'ค่ะ', 'ด้วย', 'หน่อย', 'ที', 'ตอน', 'เวลา', 'ให้', 'ผม', 'กู', 'หนู', 'ฉัน']:
                cleaned = ""
            logger.info(f"[ReminderService] Clean: fallback triggered, safe_text='{cleaned}'")
        
        cleaned_final = cleaned
        
        logger.info(f"[ReminderService] Clean: after_normalize='{cleaned_final}', date_phrase='{detected_date_phrase}', time_phrase='{detected_time_phrase}', fallback={fallback_triggered}")
        
        # ===== CALCULATE REMIND_AT =====
        # CRITICAL: User says "8 โมง" which is Bangkok time (UTC+7)
        # We need to convert Bangkok time to UTC before storing
        # HARDENING: Only calculate if time is valid
        remind_at = None
        if has_time and hour is not None and is_valid_time:
            from datetime import datetime, timedelta, timezone, date as date_type
            bangkok_offset = timedelta(hours=7)
            bangkok_tz = timezone(bangkok_offset)
            now_bkk = datetime.now(bangkok_tz)
            
            # Resolve date — relative or absolute
            if date in ("today", "tomorrow", "day_after_tomorrow") or (date == "today" and day_offset is not None):
                _day_offset = day_offset if day_offset is not None else 0
                reminder_date = now_bkk.date() + timedelta(days=_day_offset)
            elif isinstance(date, str) and len(date) == 10 and "-" in date:
                # Absolute date "YYYY-MM-DD"
                try:
                    reminder_date = date_type.fromisoformat(date)
                except (ValueError, AttributeError):
                    reminder_date = now_bkk.date()
            else:
                reminder_date = now_bkk.date()
            
            reminder_datetime_bangkok = datetime.combine(
                reminder_date,
                datetime.min.time().replace(hour=hour, minute=minute),
                tzinfo=bangkok_tz
            )
            
            # Convert to UTC for storage
            reminder_datetime_utc = reminder_datetime_bangkok.astimezone(timezone.utc)
            remind_at = reminder_datetime_utc.isoformat().replace("+00:00", "Z")
            
            logger.info(f"[ReminderService] Bangkok: {reminder_datetime_bangkok} -> UTC: {remind_at}")
        
        # HARDENING: Add validation error to result if present
        result = {
            "message": cleaned_final if cleaned_final else original_message,
            "date": date,
            "time": time,
            "has_time": has_time,
            "remind_at": remind_at
        }
        
        if not is_valid_time:
            result["validation_error"] = invalid_reason
            logger.info(f"[TimeParser] final_time=INVALID reason={invalid_reason}")
        
        return result
    
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
        
        CRITICAL: This function returns ACTION ONLY - no time prefix.
        Time prefix is added by the renderers (format_reminder_display, etc.)
        
        NEVER output "08:00 เตือน" - if no meaningful action, use original or time only.
        """
        time_val = parsed.get("time")
        raw_message = parsed.get("message", "")
        original = parsed.get("_original", "")
        
        logger.info(f"[OutputV2] Normalize: original='{original}'")
        logger.info(f"[OutputV2] Normalize: time={time_val}, raw_message='{raw_message}'")
        
        action_text = raw_message.strip()
        
        if time_val:
            action_text = self._remove_time_phrase_from_action(action_text)
            logger.info(f"[OutputV2] after_time_phrase_removal='{action_text}'")
        
        is_generic = action_text in ['นะ', 'ครับ', 'ค่ะ', 'ด้วย', 'หน่อย', 'ที', 'ตอน', 'เวลา', 'ให้', 'นี้', 'ฉัน', ''] or len(action_text) < 2
        
        if is_generic:
            action_text = self._extract_fallback_action(original, time_val is not None)
            logger.info(f"[OutputV2] extracted fallback action='{action_text}'")
        else:
            action_text = self._minimal_clean(action_text)
            logger.info(f"[OutputV2] minimal cleaned action='{action_text}'")
        
        if action_text in ['เตือน', 'ช่วย', 'แจ้ง', 'ปลุก', ''] or len(action_text) < 2:
            action_text = self._extract_fallback_action(original, time_val is not None)
            logger.info(f"[OutputV2] retry fallback action='{action_text}'")
        
        if time_val:
            action_text = self._remove_time_phrase_from_action(action_text)
            logger.info(f"[OutputV2] after_final_cleanup='{action_text}'")
        
        logger.info(f"[OutputV2] final_action_only='{action_text}'")
        return action_text if action_text else raw_message
    
    def _remove_time_phrase_from_action(self, text: str) -> str:
        """Remove time-related phrases from action text that might remain after time extraction."""
        if not text:
            return text
        
        cleaned = text
        
        time_phrase_patterns = [
            r'\d{1,2}:\d{2}',  # HH:MM pattern first
            r'\s*ตอนเย็น\s*',
            r'\s*ตอนเช้า\s*',
            r'\s*ตอนบ่าย\s*',
            r'\s*ตอนค่ำ\s*',
            r'\s*ตอน\s*',
            r'\s*เช้า\s*',
            r'\s*บ่าย\s*',
            r'\s*เย็น\s*',
            r'\s*ค่ำ\s*',
            r'\s*ทุ่ม\s*',
            r'\s*กลางคืน\s*',
            r'\s*ก่อน\s*$',
            r'\s*นี้\s*$',
        ]
        
        for pattern in time_phrase_patterns:
            cleaned = re.sub(pattern, ' ', cleaned, flags=re.IGNORECASE)
        
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        return cleaned
    
    def _extract_fallback_action(self, original: str, has_time: bool) -> str:
        """
        Extract semantic action from original message - preserve actual intent.
        
        Priority:
        1. Extract text AFTER time expressions (e.g., "8 โมงไปหาหมอ" -> "ไปหาหมอ")
        2. Remove command prefixes only (ช่วย, เตือน, etc.)
        3. Minimal clean
        
        NEVER return generic "เตือน" - prefer original message or empty.
        """
        if not original:
            return ""
        
        msg = original.strip()
        msg_lower = msg.lower()
        
        logger.info(f"[OutputV2] Extract action from: '{msg}'")
        
        extracted = None
        
        if has_time:
            extracted = self._extract_after_time(msg, msg_lower)
            if extracted and len(extracted) > 1:
                logger.info(f"[OutputV2] extracted_after_time='{extracted}'")
                return extracted
        
        command_prefixes = ['ช่วย', 'เตือน', 'แจ้งเตือน', 'อย่าลืม', 'ปลุก', 'ฉัน', 'ผม']
        
        for prefix in command_prefixes:
            if msg_lower.startswith(prefix):
                remaining = msg[len(prefix):].strip()
                if remaining and len(remaining) > 1:
                    after_time = self._extract_after_time(remaining, remaining.lower())
                    if after_time and len(after_time) > 1:
                        logger.info(f"[OutputV2] extracted_after_prefix_and_time='{after_time}'")
                        return after_time
                    logger.info(f"[OutputV2] extracted_after_prefix='{remaining}'")
                    return remaining
        
        if msg and len(msg) > 1:
            cleaned = self._minimal_clean(msg)
            if cleaned and len(cleaned) > 1:
                command_words = ['เตือน', 'ช่วย', 'แจ้ง', 'ปลุก', 'อย่าลืม']
                if cleaned.lower() in [w.lower() for w in command_words]:
                    logger.warning(f"[OutputV2] action is command word only, returning empty")
                    return ""
                logger.info(f"[OutputV2] fallback_cleaned='{cleaned}'")
                return cleaned
        
        logger.warning(f"[OutputV2] Could not extract semantic action, returning empty")
        return ""
    
    def _extract_after_time(self, text: str, text_lower: str) -> str:
        """Extract action text appearing after time expression."""
        time_patterns = [
            r'\d{1,2}\s*โมงเย็น',
            r'\d{1,2}\s*โมงเช้า', 
            r'\d{1,2}\s*โมง',
            r'\d{1,2}:\d{2}',
            r'ตอน\s*\d{1,2}',
            r'เวลา\s*\d{1,2}',
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, text_lower)
            if match:
                after = text[match.end():].strip()
                if after:
                    after = self._minimal_clean(after)
                    return after
        
        return ""  # Return empty if no time pattern found
    
    def _minimal_clean(self, text: str) -> str:
        """Minimal clean - only remove obvious scaffolding, preserve meaning."""
        if not text:
            return ""
        
        cleaned = text.strip()
        
        to_remove_start = [
            'ฉัน', 'ผม', 'คุณ', 'ด้วย', 'นะ', 'ครับ', 'ค่ะ', 'หน่อย',
            'ของ', 'วันนี้', 'วันพรุ่งนี้', 'พรุ่งนี้', 'ที', 'นี้',
            'ช่วยเตือน', 'เพิ่มนัด', 'นัดหมาย', 'แจ้งเตือน'
        ]
        
        for w in to_remove_start:
            if cleaned.lower().startswith(w):
                cleaned = cleaned[len(w):].strip()
        
        to_remove_patterns = [
            r'^ตอน\s*', r'^เวลา\s*', r'^ของ\s*',
            r':\d{2}\s*', r':00\s*',
        ]
        
        for pat in to_remove_patterns:
            cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE)
        
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        cleaned = re.sub(r'^[^\w\u0e00-\u0fff]+', '', cleaned)
        
        generic_only = ['เตือน', 'ช่วย', 'แจ้ง', 'ปลุก', 'นะ', 'ครับ', 'ค่ะ', '']
        if cleaned in generic_only:
            return ""
        
        return cleaned
    
    def _clean_action_text(self, text: str) -> str:
        """Remove common Thai fragments and clean action text."""
        if not text:
            return "เตือน"
        
        cleaned = text.strip()
        
        fragments_to_remove = [
            r'^ช่วย\s*', r'^เตือน\s*', r'^แจ้งเตือน\s*', r'^อย่าลืม\s*', r'^ปลุก\s*',
            r'^ฉัน\s*', r'^ผม\s*', r'^คุณ\s*',
            r'\s*ตอน\s+.*$', r'\s*เวลา\s+.*$', r'\s*ของ\s+.*$', r'\s*นี้\s*$',
            r'\s*วันนี้\s*$', r'\s*พรุ่งนี้\s*$', r'\s*วันพรุ่งนี้\s*$',
            r'^ตอน\s*', r'^เวลา\s*', r'^ของ\s*', r'^นี้\s*',
        ]
        
        for pattern in fragments_to_remove:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        forbidden = ['นะ', 'ครับ', 'ค่ะ', 'ด้วย', 'หน่อย', 'ที', 'ตอน', 'เวลา', 'ให้', 'นี้', 'ฉัน', '']
        if cleaned in forbidden or len(cleaned) < 2:
            return "เตือน"
        
        return cleaned
    
    def _parse_specific_date(self, message: str) -> Optional[str]:
        """
        Parse specific date expressions like '5 เมษา', '1 Apr', 'Apr 5', 'วันที่ 5 เม.ย.'.
        Returns "YYYY-MM-DD" string or None.
        If date has passed this year, auto-advances to next year.
        """
        msg_clean = message.lower().strip()
        # Remove common prefix words
        msg_clean = re.sub(r'วันที่\s*', '', msg_clean)
        
        # Sort by length descending to match longest name first (e.g., "มกราคม" before "มกรา")
        for month_name, month_num in sorted(MONTH_NAMES.items(), key=lambda x: -len(x[0])):
            escaped = re.escape(month_name)
            
            # Day before month: "5 เมษา", "5apr", "5 apr", "5 เมษาเวลา"
            # Removed (?!\w) because it blocks matching Thai words that aren't space-separated.
            # Using negative lookahead for English letters only to avoid matching "1 Apr" from "1 April" (though sorted length helps).
            lookahead = r'(?![a-zA-Z])' if re.match(r'^[a-zA-Z]+$', month_name) else ''
            
            m = re.search(r'(\d{1,2})\s*' + escaped + lookahead, msg_clean)
            if m:
                day = int(m.group(1))
                result = self._resolve_year(month_num, day)
                if result:
                    logger.info(f"[SpecificDate] parsed '{month_name}' day={day} -> {result}")
                    return result
                    
            # Month before day: "เมษา 5", "apr 5"
            m = re.search(escaped + r'\s*(\d{1,2})(?!\d)', msg_clean)
            if m:
                day = int(m.group(1))
                result = self._resolve_year(month_num, day)
                if result:
                    logger.info(f"[SpecificDate] parsed '{month_name}' day={day} -> {result}")
                    return result
        
        return None
    
    def _resolve_year(self, month: int, day: int) -> Optional[str]:
        """Return 'YYYY-MM-DD', choosing next year if date has already passed this year."""
        from datetime import date as date_type
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Bangkok")).date()
        try:
            target = date_type(now.year, month, day)
            if target < now:
                target = date_type(now.year + 1, month, day)
            return target.isoformat()
        except ValueError:
            logger.warning(f"[SpecificDate] Invalid date: month={month} day={day}")
            return None
    
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
            msg = item['message']
            time_str = item['time_str']
            msg = self._strip_leading_time_duplication(msg, time_str)
            lines.append(f"  • {time_str} {msg}")
        
        if untimed:
            lines.append("")
            lines.append("📝 อื่นๆ:")
            for item in untimed:
                lines.append(f"  • {item['message']}")
        
        return "\n".join(lines)
    
    def format_reminder_display(self, reminder: Dict[str, Any]) -> str:
        """
        Format a full reminder for user-facing display (morning/daily summary).
        
        Applies normalization and adds time prefix from remind_at.
        
        CRITICAL: Backward-compatible safeguard - strip duplicated leading time
        if the stored message already starts with a time pattern like "09:00 ...".
        
        Returns:
            Formatted string like "19:00 - กินข้าวกับพ่อ"
            Or empty string if reminder cannot be rendered properly
        """
        raw_message = reminder.get("message", "")
        remind_at = reminder.get("remind_at", "")
        
        logger.info(f"[MorningSummaryRender] raw_message={raw_message[:50]}")
        
        if not raw_message or len(raw_message.strip()) < 2:
            logger.info(f"[MorningSummaryRender] skipped=True reason=empty_message")
            return ""
        
        time_prefix = None
        if remind_at:
            try:
                dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00")).astimezone(BANGKOK_TZ)
                time_prefix = dt.strftime("%H:%M")
                logger.info(f"[MorningSummaryRender] time_prefix={time_prefix} from_remind_at={remind_at[:20]}")
            except Exception as e:
                logger.warning(f"[MorningSummaryRender] time_parse_error={e}")
        
        parsed_for_normalize = {
            "message": raw_message,
            "time": time_prefix,
            "_original": raw_message
        }
        
        normalized_message = self.normalize_reminder_display(parsed_for_normalize)
        logger.info(f"[MorningSummaryRender] normalized_message={normalized_message[:50]}")
        
        if time_prefix:
            normalized_message = self._strip_leading_time_duplication(normalized_message, time_prefix)
            logger.info(f"[MorningSummaryRender] after_dedup_cleanup={normalized_message[:50]}")
        
        if time_prefix and normalized_message and len(normalized_message.strip()) > 1:
            final_render = f"{time_prefix} - {normalized_message}"
            logger.info(f"[MorningSummaryRender] final_render={final_render[:50]}")
            return final_render
        elif normalized_message and len(normalized_message.strip()) > 1:
            return normalized_message
        else:
            logger.info(f"[MorningSummaryRender] skipped=True reason=no_valid_render")
            return ""
    
    def _strip_leading_time_duplication(self, message: str, time_prefix: str) -> str:
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
        
        time_pattern = re.match(r'^\d{2}:\d{2}[\s\-:]*', message_stripped)
        if time_pattern:
            remaining = message_stripped[time_pattern.end():].strip()
            remaining = re.sub(r'^[\s\-:]+', '', remaining)
            if remaining:
                logger.info(f"[DedupSafeguard] found different leading time, stripping it")
                return remaining
        
        message_stripped = re.sub(r'^[^\w\u0e00-\u0fff]+', '', message_stripped)
        
        return message_stripped if message_stripped else message


reminder_service = ReminderService()
