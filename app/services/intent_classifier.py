"""
Intent Classifier Service - AI-based intent classification.

Flow:
1. Explicit patterns (fast regex) - handled in command_detector.py
2. AI classification (this service) - for ambiguous cases
3. Keyword fallback - last resort
"""
import hashlib
import time
import httpx
import logging
from typing import Optional, Dict, Any
from app.config import Settings

_settings = Settings()
logger = logging.getLogger(__name__)

_intent_cache: Dict[str, tuple[str, float]] = {}
CACHE_TTL = 3600

INTENTS = [
    "add_task",
    "add_pantry", 
    "create_reminder",
    "list_tasks",
    "list_pantry",
    "connect_calendar",
    "sync_calendar",
    "agenda_query",
    "chat"
]

SYSTEM_PROMPT = """Classify this Thai message into ONE of these intents:
- add_task (เพิ่มงาน, จดงาน, ภารกิจ, todo, ต้องทำ, ลิสต์)
- add_pantry (ซื้อของ, เพิ่มของ, ของกิน, ของในตู้เย็น, ครัว)
- create_reminder (เน้นคำว่า: เตือน, แจ้งเตือน, อย่าลืม, ช่วยเตือน, ปลุก)
- list_tasks (ดูงาน, รายการงาน, มีงานอะไรบ้าง)
- list_pantry (ดูตู้เย็น, ของหมดอายุ, ของในตู้เย็นมีอะไรบ้าง)
- connect_calendar (เชื่อมต่อปฏิทิน, ต่อ Google Calendar, ผูกบัญชีปฏิทิน)
- sync_calendar (ซิงค์ปฏิทิน, อัปเดตข้อมูลปฏิทิน, ถึงนัดหมายจาก Google)
- agenda_query (ดูตารางวันนี้, พรุ่งนี้มีนัดอะไรบ้าง, สรุปงานวันนี้, มีประชุมอะไรบ้าง)
- chat (คำถามทั่วไปที่ไม่เกี่ยวกับเลขา, คุยเล่น, ทักทาย, ถามเวลาที่อื่นๆ, ถามความรู้ทั่วไป)

Respond with ONLY the intent word, nothing else.
Example: add_task"""


def _get_cache_key(message: str) -> str:
    """Generate cache key from message."""
    return hashlib.md5(message.encode()).hexdigest()


def _is_cache_valid(cached: tuple[str, float]) -> bool:
    """Check if cache entry is still valid."""
    return time.time() - cached[1] < CACHE_TTL


def classify_intent(message: str) -> Optional[str]:
    """
    Classify user message intent using AI.
    
    Returns:
        Intent string or None if classification fails
    """
    if not _settings.openai_api_key:
        logger.warning("[IntentClassifier] No API key, skipping AI classification")
        return None
    
    message = message.strip()
    if not message:
        return None
    
    cache_key = _get_cache_key(message)
    
    if cache_key in _intent_cache:
        cached_intent, cached_time = _intent_cache[cache_key]
        if _is_cache_valid((cached_intent, cached_time)):
            logger.info(f"[IntentClassifier] Cache hit: {cached_intent}")
            return cached_intent
    
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {_settings.openai_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message}
        ],
        "temperature": 0,
        "max_tokens": 10
    }
    
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            intent = data["choices"][0]["message"]["content"].strip().lower()
            
            if intent in INTENTS:
                _intent_cache[cache_key] = (intent, time.time())
                logger.info(f"[IntentClassifier] Classified: {intent}")
                return intent
            else:
                logger.warning(f"[IntentClassifier] Unknown intent: {intent}")
        else:
            logger.error(f"[IntentClassifier] API error: {response.status_code}")
    except Exception as e:
        logger.error(f"[IntentClassifier] Exception: {e}")
    
    return None


def extract_fields_for_intent(message: str, intent: str) -> Dict[str, Any]:
    """Extract relevant fields based on intent."""
    from app.services.reminder_service import reminder_service
    
    if intent == "create_reminder":
        parsed = reminder_service.parse_reminder_message(message)
        remind_at = None
        if parsed.get("date") and parsed.get("time"):
            remind_at = reminder_service.calculate_remind_at(
                parsed.get("date"), 
                parsed.get("time")
            )
        return {
            "message": parsed.get("message", message),
            "date": parsed.get("date"),
            "time": parsed.get("time"),
            "has_time": parsed.get("has_time", False),
            "remind_at": remind_at
        }
    
    if intent == "add_task":
        title = message
        for prefix in ["เพิ่มงาน", "เพิ่ม", "งาน"]:
            if title.startswith(prefix):
                title = title[len(prefix):].strip()
        return {"title": title or message}
    
    if intent == "add_pantry":
        item = message
        for prefix in ["ซื้อ", "เพิ่ม", "บันทึก"]:
            if item.startswith(prefix):
                item = item[len(prefix):].strip()
        return {"item_name": item or message}
    
    return {}



