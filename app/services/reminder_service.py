"""
Reminder service for managing user reminders.
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import re
import logging

logger = logging.getLogger(__name__)


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
        cleaned = message_lower
        
        # FIRST: Remove reminder command words (before anything else)
        # More aggressive - remove "ช่วย" prefix separately
        cleaned = re.sub(r'^ช่วย\s+', '', cleaned)
        cleaned = re.sub(r'^(เตือน|แจ้งเตือน)\s*', '', cleaned)
        cleaned = re.sub(r'\s+(เตือน|แจ้งเตือน)\s+', ' ', cleaned)
        cleaned = re.sub(r'^(อย่าลืม)\s*', '', cleaned)
        
        # Also remove common fillers at start
        cleaned = re.sub(r'^(หน่อย|นะ|ครับ|ค่ะ|ด้วย)\s*', '', cleaned)
        
        # Remove time words EXHAUSTIVELY
        time_words = [
            'บ่ายสอง', 'บ่าย2', 'บ่าย 2', 'บ่ายสองโมง',
            'บ่ายสาม', 'บ่าย3', 'บ่าย 3', 'บ่ายสามโมง',
            'บ่ายสี่', 'บ่าย4', 'บ่าย 4', 'บ่ายสี่โมง',
            'บ่ายห้า', 'บ่าย5', 'บ่าย 5',
            'บ่าย', 'ตอนบ่าย',
            'เช้า', 'เช้ามาก', 'ตอนเช้า', 'โมงเช้า',
            'เย็น', 'ตอนเย็น', 'โมงเย็น',
            'ทุ่ม', 'ตอนทุ่ม',
            'ตีหนึ่ง', 'ตี1', 'ตีสอง', 'ตี2', 'ตีสาม', 'ตี3',
            'ตีสี่', 'ตี4', 'ตีห้า', 'ตี5',
            'ตีหก', 'ตี6', 'ตีเจ็ด', 'ตี7', 'ตีแปด', 'ตี8',
            'ตีเก้า', 'ตี9', 'ตีสิบ', 'ตี10',
        ]
        for tw in time_words:
            cleaned = cleaned.replace(tw, ' ')
        
        # Remove X โมง patterns
        cleaned = re.sub(r'\d{1,2}\s*โมง', ' ', cleaned)
        # Remove X ทุ่ม patterns
        cleaned = re.sub(r'\d{1,2}\s*ทุ่ม', ' ', cleaned)
        # Remove ตีX patterns
        cleaned = re.sub(r'ตี\d{1,2}', ' ', cleaned)
        # Remove X นาที patterns
        cleaned = re.sub(r'\d{1,2}\s*นาที', ' ', cleaned)
        
        # Remove standalone numbers (orphaned after time word removal)
        cleaned = re.sub(r'(^|\s)\d+(\s|$)', ' ', cleaned)
        
        # Remove pronouns
        for pronoun in ['ฉัน', 'ผม', 'เขา', 'คุณ', 'ด้วย', 'นะ', 'ครับ', 'ค่ะ']:
            if cleaned.startswith(pronoun):
                cleaned = cleaned[len(pronoun):]
        cleaned = re.sub(r'\s+(ฉัน|ผม|เขา|คุณ|ด้วย|นะ|ครับ|ค่ะ)\b', ' ', cleaned)
        
        # Remove date words
        cleaned = re.sub(r'(พรุ่งนี้|วันพรุ่ง|มะรืนนี้|วันนี้)', '', cleaned)
        
        # Remove HH:MM
        cleaned = re.sub(r'\d{1,2}:\d{2}', ' ', cleaned)
        
        # Final cleanup
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        logger.info(f"[ReminderService] Cleaned message: '{cleaned}'")
        
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
            "message": cleaned if cleaned else original_message,
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
        """Create a reminder for the user."""
        if remind_at is None:
            remind_at = self.parse_reminder_time(message)
        
        if remind_at is None:
            # Default to tomorrow 9:00
            remind_at = datetime.now() + timedelta(days=1)
            remind_at = remind_at.replace(hour=9, minute=0, second=0, microsecond=0)
        
        reminder_message = self.extract_reminder_message(message)
        
        return {
            "user_id": user_id,
            "message": reminder_message,
            "remind_at": remind_at.isoformat(),
            "status": "pending"
        }
    
    def format_reminder_response(self, reminder: Dict[str, Any]) -> str:
        """Format reminder as response string."""
        remind_at = reminder.get("remind_at", "")
        message = reminder.get("message", "ไม่ระบุ")
        
        try:
            dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
            # Convert to Bangkok timezone
            bangkok_time = dt.astimezone() if dt.tzinfo else dt
            formatted_date = bangkok_time.strftime("%d/%m/%Y เวลา %H:%M น.")
        except Exception:
            formatted_date = remind_at
        
        return f"✅ เตือน '{message}' ไว้เมื่อ {formatted_date} ครับ!"


reminder_service = ReminderService()
