"""
Date Validation Service for Thai LINE Personal Secretary

Provides centralized date resolution and validation for all appointment/reminder/task creation flows.
Uses Bangkok timezone (UTC+7) consistently.

Business Rules:
- Only dates within CURRENT YEAR are allowed
- Do NOT silently guess ambiguous dates
- Invalid or past dates must not be saved to DB

Result Statuses:
- "resolved": Valid date that can be saved
- "needs_clarification": Ambiguous, requires user input
- "invalid": Cannot create (past year, invalid date)
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, date, timedelta, timezone
import re
import logging

logger = logging.getLogger(__name__)

# Bangkok timezone
BANGKOK_TZ = timezone(timedelta(hours=7))

# Thai month mappings
THAI_MONTHS = {
    'มกรา': 1, 'มคอ': 1, 'มกราคม': 1,
    'กุมภา': 2, 'กพ': 2, 'กุมภาพันธ์': 2,
    'มีนา': 3, 'มีค': 3, 'มีนาคม': 3,
    'เมษา': 4, 'เมย': 4, 'เมษายน': 4,
    'พฤษภา': 5, 'พค': 5, 'พฤษภาคม': 5,
    'มิถุนา': 6, 'มิย': 6, 'มิถุนายน': 6,
    'กรกฎา': 7, 'กค': 7, 'กรกฎาคม': 7,
    'สิงหา': 8, 'สค': 8, 'สิงหาคม': 8,
    'กันยา': 9, 'กย': 9, 'กันยายน': 10,
    'ตุลา': 10, 'ตค': 10, 'ตุลาคม': 10,
    'พฤศจิกา': 11, 'พย': 11, 'พฤศจิกายน': 11,
    'ธันวา': 12, 'ธค': 12, 'ธันวาคม': 12
}

# Days per month (non-leap year)
DAYS_IN_MONTH = {
    1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31
}

# Days per month (leap year)
DAYS_IN_MONTH_LEAP = {
    1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31
}

# Thai day of week
THAI_WEEKDAYS = {
    'วันจันทร์': 0,
    'วันอังคาร': 1,
    'วันพุธ': 2,
    'วันพฤหัสบดี': 3,
    'วันศุกร์': 4,
    'วันเสาร์': 5,
    'วันอาทิตย์': 6
}

# Weekend patterns
WEEKEND_PATTERNS = ['เสาร์อาทิตย์', 'สุดสัปดาห์', 'วันหยุด']
WEEKEND_DAYS = ['เสาร์', 'อาทิตย์', 'เสาร์อาทิตย์']


def get_bangkok_now() -> datetime:
    """Get current datetime in Bangkok timezone."""
    return datetime.now(BANGKOK_TZ)


def get_bangkok_date() -> date:
    """Get current date in Bangkok timezone."""
    return get_bangkok_now().date()


def is_leap_year(year: int) -> bool:
    """Check if year is a leap year."""
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def get_days_in_month(month: int, year: int) -> int:
    """Get number of days in a month."""
    if is_leap_year(year):
        return DAYS_IN_MONTH_LEAP.get(month, 30)
    return DAYS_IN_MONTH.get(month, 30)


def parse_thai_month(month_text: str) -> Optional[int]:
    """Parse Thai month text to month number."""
    month_lower = month_text.lower().strip()
    return THAI_MONTHS.get(month_lower)


def parse_explicit_date(message: str) -> Optional[Dict[str, Any]]:
    """
    Parse explicit date patterns like "วันที่ 31 มีนา" or "31 มีนา".
    
    Returns:
        dict with keys: day, month, year (optional)
    """
    # Pattern: "วันที่ X" or just "X" followed by month
    patterns = [
        r'วันที่\s*(\d+)',
        r'(\d+)\s*(?=มกรา|กุมภา|มีนา|เมษา|พฤษภา|มิถุนา|กรกฎา|สิงหา|กันยา|ตุลา|พฤศจิกา|ธันวา)',
        r'^(\d+)$'
    ]
    
    day = None
    month = None
    year = None
    
    # Extract day
    for pattern in patterns[:2]:
        match = re.search(pattern, message)
        if match:
            day = int(match.group(1))
            break
    
    # Extract month
    for thai_month, month_num in THAI_MONTHS.items():
        if thai_month in message:
            month = month_num
            break
    
    # Extract year (if present)
    year_pattern = r'(?:ปี\s*)?(\d{4})'
    year_match = re.search(year_pattern, message)
    if year_match:
        year = int(year_match.group(1))
    
    if day is not None:
        return {"day": day, "month": month, "year": year}
    
    return None


def resolve_relative_date(message: str) -> Optional[str]:
    """
    Resolve relative date phrases like พรุ่งนี้, มะรืนนี้, วันนี้.
    
    Returns:
        "today", "tomorrow", "day_after_tomorrow", or None
    """
    msg_lower = message.lower()
    
    if 'พรุ่งนี้' in msg_lower or 'วันพรุ่ง' in msg_lower:
        return "tomorrow"
    elif 'มะรืนนี้' in msg_lower or 'มะรืน' in msg_lower:
        return "day_after_tomorrow"
    elif 'วันนี้' in msg_lower:
        return "today"
    
    return None


def resolve_weekend_ambiguity(message: str) -> Optional[List[date]]:
    """
    Check if message contains weekend ambiguity and return possible dates.
    
    Returns:
        List of possible dates [saturday, sunday] or None
    """
    msg_lower = message.lower()
    
    # Check for weekend patterns
    has_weekend = any(pattern in msg_lower for pattern in WEEKEND_PATTERNS)
    has_sat = 'เสาร์' in msg_lower
    has_sun = 'อาทิตย์' in msg_lower
    
    if not (has_weekend or has_sat or has_sun):
        return None
    
    # Get current date and find next Saturday and Sunday
    today = get_bangkok_date()
    current_weekday = today.weekday()  # 0=Monday, 6=Sunday
    
    # Calculate days until Saturday (5) and Sunday (6)
    days_to_sat = (5 - current_weekday) % 7
    days_to_sun = (6 - current_weekday) % 7
    
    # If today is weekend, get next weekend
    if days_to_sat == 0:
        days_to_sat = 7
    if days_to_sun == 0:
        days_to_sun = 7
    
    saturday = today + timedelta(days=days_to_sat)
    sunday = today + timedelta(days=days_to_sun)
    
    return [saturday, sunday]


def validate_and_resolve_date(
    message: str,
    reference_date: Optional[date] = None
) -> Dict[str, Any]:
    """
    Main date validation and resolution function.
    
    Args:
        message: User message containing date information
        reference_date: Optional reference date (defaults to Bangkok now)
    
    Returns:
        dict with keys:
        - status: "resolved" | "needs_clarification" | "invalid"
        - resolved_date: Optional[date]
        - reason: Optional[str]
        - clarification_question: Optional[str]
        - options: Optional[List[date]]
    """
    msg_lower = message.lower().strip()
    
    # Default reference date is Bangkok today
    if reference_date is None:
        reference_date = get_bangkok_date()
    
    current_year = reference_date.year
    
    logger.info(f"[DateValidation] raw_input={message}")
    logger.info(f"[DateValidation] reference_date={reference_date}")
    
    # ============================================================
    # Check for weekend ambiguity FIRST
    # ============================================================
    weekend_options = resolve_weekend_ambiguity(message)
    if weekend_options:
        logger.info(f"[DateValidation] status=needs_clarification reason=weekend_ambiguity")
        return {
            "status": "needs_clarification",
            "resolved_date": None,
            "reason": "weekend_ambiguity",
            "clarification_question": f"ต้องการวันเสาร์ที่ {weekend_options[0].strftime('%d %m')}, วันอาทิตย์ที่ {weekend_options[1].strftime('%d %m')} หรือทั้งสองวันครับ?",
            "options": weekend_options
        }
    
    # ============================================================
    # Check for relative date (พรุ่งนี้, มะรืนนี้, วันนี้)
    # ============================================================
    relative_date = resolve_relative_date(message)
    if relative_date:
        # Calculate the actual date
        day_offset = 0
        if relative_date == "tomorrow":
            day_offset = 1
        elif relative_date == "day_after_tomorrow":
            day_offset = 2
        
        resolved = reference_date + timedelta(days=day_offset)
        
        # Validate: must be in current year
        if resolved.year != current_year:
            logger.info(f"[DateValidation] status=invalid reason=next_year_not_allowed")
            return {
                "status": "invalid",
                "resolved_date": None,
                "reason": "next_year_not_allowed",
                "clarification_question": None,
                "options": None
            }
        
        # Validate: must not be in the past
        if resolved < reference_date:
            logger.info(f"[DateValidation] status=invalid reason=past_date")
            return {
                "status": "invalid",
                "resolved_date": None,
                "reason": "past_date",
                "clarification_question": None,
                "options": None
            }
        
        logger.info(f"[DateValidation] status=resolved resolved_date={resolved}")
        return {
            "status": "resolved",
            "resolved_date": resolved,
            "reason": "relative_date",
            "clarification_question": None,
            "options": None
        }
    
    # ============================================================
    # Check for explicit date (day + month + optional year)
    # ============================================================
    explicit = parse_explicit_date(message)
    
    if explicit and explicit.get('day') is not None:
        day = explicit['day']
        month = explicit.get('month')
        year = explicit.get('year')  # Will default to current_year later
        
        logger.info(f"[DateValidation] parsed_components=day={day}, month={month}, year={year}")
        
        # Track if month was originally missing
        month_was_missing = month is None
        
        # Check for missing month - default to current month for validation
        # This allows us to check if date is in the past
        if month is None:
            # Default to current month to check if day is valid in current month
            # and if the date is in the past
            month = reference_date.month
            logger.info(f"[DateValidation] Defaulting to current month {month} for validation")
        
        # Default year to current year if not specified
        if year is None:
            year = current_year
        
        # If month was originally missing, check if date is in the past
        if month_was_missing:
            # Create a tentative date to check if it's in the past
            try:
                tentative_date = date(year, month, day)
                if tentative_date < reference_date:
                    # Past date - reject
                    logger.info(f"[DateValidation] status=invalid reason=past_date_no_month")
                    return {
                        "status": "invalid",
                        "resolved_date": None,
                        "reason": "past_date",
                        "clarification_question": None,
                        "options": None
                    }
                # If tentative date is today, accept it (same-day appointments allowed)
                if tentative_date == reference_date:
                    logger.info(f"[DateValidation] status=resolved reason=same_day_implicit")
                    return {
                        "status": "resolved",
                        "resolved_date": tentative_date,
                        "reason": "same_day_implicit",
                        "clarification_question": None,
                        "options": None
                    }
            except ValueError:
                pass
            
            # Future date - ask for clarification
            logger.info(f"[DateValidation] status=needs_clarification reason=missing_month")
            return {
                "status": "needs_clarification",
                "resolved_date": None,
                "reason": "missing_month",
                "clarification_question": f"วันที่ {day} ของเดือนไหนครับ?",
                "options": None
            }
        
        # Validate day number
        if day < 1 or day > 31:
            logger.info(f"[DateValidation] status=needs_clarification reason=invalid_day_number")
            return {
                "status": "needs_clarification",
                "resolved_date": None,
                "reason": "invalid_day_number",
                "clarification_question": f"วันที่ {day} ไม่ถูกต้อง กรุณาระบุวันที่ 1-31 ครับ",
                "options": None
            }
        
        # Validate month-day combination only if month is known
        if month is not None:
            max_days = get_days_in_month(month, year)
            if day > max_days:
                month_names_list = {1: 'มกรา', 2: 'กุมภา', 3: 'มีนา', 4: 'เมษา', 5: 'พฤษภา', 6: 'มิถุนา',
                              7: 'กรกฎา', 8: 'สิงหา', 9: 'กันยา', 10: 'ตุลา', 11: 'พฤศจิกา', 12: 'ธันวา'}
                month_name = month_names_list.get(month, str(month))
                logger.info(f"[DateValidation] status=needs_clarification reason=day_exceeds_month_days max_days={max_days}")
                return {
                    "status": "needs_clarification",
                    "resolved_date": None,
                    "reason": "day_exceeds_month_days",
                    "clarification_question": f"เดือน{month_name}มี{max_days}วัน กรุณาระบุวันที่ที่ถูกต้องครับ",
                    "options": None
                }
        
        # Validate year
        if year != current_year:
            logger.info(f"[DateValidation] status=invalid reason=year_not_current year={year}")
            return {
                "status": "invalid",
                "resolved_date": None,
                "reason": "year_not_allowed",
                "clarification_question": None,
                "options": None
            }
        
        # Create the resolved date
        if month is None:
            return {
                "status": "needs_clarification",
                "resolved_date": None,
                "reason": "missing_month",
                "clarification_question": f"วันที่ {day} ของเดือนไหนครับ?",
                "options": None
            }
        
        try:
            resolved = date(year, month, day)
        except ValueError:
            logger.info(f"[DateValidation] status=invalid reason=invalid_date_combo")
            return {
                "status": "invalid",
                "resolved_date": None,
                "reason": "invalid_date_combo",
                "clarification_question": None,
                "options": None
            }
        
        # Validate: must not be in the past
        if resolved < reference_date:
            logger.info(f"[DateValidation] status=invalid reason=past_date resolved={resolved} reference={reference_date}")
            return {
                "status": "invalid",
                "resolved_date": None,
                "reason": "past_date",
                "clarification_question": None,
                "options": None
            }
        
        logger.info(f"[DateValidation] status=resolved resolved_date={resolved}")
        return {
            "status": "resolved",
            "resolved_date": resolved,
            "reason": "explicit_date",
            "clarification_question": None,
            "options": None
        }
    
    # ============================================================
    # Check for weekday reference (วันจันทร์, วันอังคาร, etc.)
    # ============================================================
    for weekday_name, weekday_num in THAI_WEEKDAYS.items():
        if weekday_name in msg_lower:
            # Find the next occurrence of this weekday
            today_weekday = reference_date.weekday()
            days_until = (weekday_num - today_weekday) % 7
            if days_until == 0:
                days_until = 7  # Next week
            
            resolved = reference_date + timedelta(days=days_until)
            
            # Validate: must be in current year
            if resolved.year != current_year:
                return {
                    "status": "invalid",
                    "resolved_date": None,
                    "reason": "next_year_not_allowed",
                    "clarification_question": None,
                    "options": None
                }
            
            return {
                "status": "resolved",
                "resolved_date": resolved,
                "reason": "weekday_reference",
                "clarification_question": None,
                "options": None
            }
    
    # ============================================================
    # No date detected
    # ============================================================
    logger.info(f"[DateValidation] status=needs_clarification reason=no_date_detected")
    return {
        "status": "needs_clarification",
        "resolved_date": None,
        "reason": "no_date_detected",
        "clarification_question": "ต้องการนัดวันไหนครับ? (วันนี้/พรุ่งนี้/วันที่ XX เดือน XX)",
        "options": None
    }


def format_date_thai(date_obj: date) -> str:
    """Format date in Thai format."""
    month_names = {
        1: 'มกรา', 2: 'กุมภา', 3: 'มีนา', 4: 'เมษา', 5: 'พฤษภา', 6: 'มิถุนา',
        7: 'กรกฎา', 8: 'สิงหา', 9: 'กันยา', 10: 'ตุลา', 11: 'พฤศจิกา', 12: 'ธันวา'
    }
    return f"{date_obj.day} {month_names.get(date_obj.month, str(date_obj.month))} {date_obj.year}"


def format_date_response(date_obj: date) -> str:
    """Format date for user-facing response."""
    return date_obj.strftime("%d/%m/%Y")