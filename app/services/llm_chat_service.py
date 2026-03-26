"""
LLM Chat Service for Assistant Chat Mode.
Provides natural conversation when no command is detected.
"""
import os
import re
import httpx
import logging
from typing import Optional, List, Dict, Any
from app.config import Settings

_settings = Settings()
logger = logging.getLogger(__name__)

# In-memory conversation history per user
# Format: {line_user_id: [{"role": "user"/"assistant", "content": "..."}]}
_conversation_histories: Dict[str, List[Dict[str, str]]] = {}

# Max turns to keep in history
MAX_HISTORY_TURNS = 4


PARKING_UPDATE_PATTERNS = [
    r"จอดรถชั้น\s*([0-9A-Za-zก-๙]+)",
    r"จอดรถ\s*ชั้น\s*([0-9A-Za-zก-๙]+)",
    r"รถอยู่ชั้น\s*([0-9A-Za-zก-๙]+)",
    r"จอดรถไว้\s*ชั้น\s*([0-9A-Za-zก-๙]+)",
    r"จอดรถไว้\s*([0-9A-Za-zก-๙]+)",
    r"จอดรถ\s*([0-9A-Za-zก-๙]{1,5})$",
    r"จอด\s*ชั้น\s*([0-9A-Za-zก-๙]+)",
    r"จอด\s*([A-Za-z0-9ก-๙]{1,5})$",
    r"parking\s*([A-Za-z0-9ก-๙]{1,5})$",
    r"ผมจอดรถชั้น\s*([0-9A-Za-zก-๙]+)",
    r"ผมจอดรถ\s*ชั้น\s*([0-9A-Za-zก-๙]+)",
    r"ผมจอดรถ\s*([A-Za-z0-9ก-๙]{1,5})$",
    r"วันนี้จอดรถชั้น\s*([0-9A-Za-zก-๙]+)",
    r"วันนี้จอดรถ\s*ชั้น\s*([0-9A-Za-zก-๙]+)",
    r"วันนี้จอดรถ\s*([A-Za-z0-9ก-๙]{1,5})$",
    r"วันนี้ผมจอดรถชั้น\s*([0-9A-Za-zก-๙]+)",
    r"วันนี้ผมจอดรถ\s*ชั้น\s*([0-9A-Za-zก-๙]+)",
    r"วันนี้ผมจอดรถ\s*([A-Za-z0-9ก-๙]{1,5})$",
]

PARKING_QUERY_PATTERNS = [
    r"จอดรถไว้ตรงไหน",
    r"รถจอดไว้ที่ไหน",
    r"รถอยู่ไหน",
    r"จอดรถที่ไหน",
    r"รถอยู่ที่ไหน",
    r"จอดรถชั้นไหน",
    r"จอดรถไหน",
    r"ผมจอดรถไว้ไหน",
    r"รถอยู่ตรงไหน",
    r"parking\s*where",
    r"where\s*parking",
]

PARKING_EXCLUDE_WORDS = [
    "ไหน", "ที่ไหน", "ตรงไหน", "อยู่ไหน", "ชั้นไหน", "ไหนครับ", "ไหนคะ",
    "where", "which", "location", "ที่", "อยู่"
]


def is_parking_query_text(text: str) -> bool:
    """Check if text is a parking query (question)."""
    return any(re.search(p, text.lower()) for p in PARKING_QUERY_PATTERNS)


def has_excluded_word(text: str) -> bool:
    """Check if text contains query/exclusion words."""
    lower = text.lower()
    return any(excl in lower for excl in PARKING_EXCLUDE_WORDS)


def detect_parking_update(message: str) -> Optional[str]:
    """Detect if message is a parking location UPDATE (not query)."""
    msg_lower = message.lower().strip()
    
    if is_parking_query_text(message):
        logger.info(f"[LLMChat] Parking intent detected: query (will NOT save)")
        return None
    
    for pattern in PARKING_UPDATE_PATTERNS:
        match = re.search(pattern, msg_lower)
        if match:
            location = match.group(1).strip()
            
            if has_excluded_word(location):
                logger.info(f"[LLMChat] Parking intent skipped: contains excluded word, location={location}")
                return None
            
            if location and 1 <= len(location) <= 10:
                logger.info(f"[LLMChat] Parking intent detected: update, location={location}")
                return location
    
    return None


def detect_parking_query(message: str) -> bool:
    """Detect if message is a parking location QUERY."""
    return is_parking_query_text(message)


def handle_parking_memory(line_user_id: str, user_message: str, user_id: str) -> Optional[str]:
    """Handle parking memory: save updates, answer queries from DB."""
    msg_lower = user_message.lower().strip()
    
    update_location = detect_parking_update(user_message)
    
    logger.info(f"[LLMChat] Parking handle: user_id={user_id}, message='{msg_lower[:30]}', update_location={update_location}")
    
    if update_location:
        normalized_location = normalize_parking_location(update_location)
        logger.info(f"[LLMChat] Parking normalized: '{update_location}' -> '{normalized_location}'")
        
        from app.agents.memory_manager import add_persistent_memory
        try:
            add_persistent_memory(user_id, "parking", f"จอดรถที่ชั้น {normalized_location}")
            logger.info(f"[LLMChat] Parking DB save SUCCESS: user_id={user_id}, location={normalized_location}")
            return f"โอเคครับ จอดที่ชั้น {normalized_location} นะครับ"
        except Exception as e:
            logger.error(f"[LLMChat] Parking DB save FAILED: user_id={user_id}, error={e}")
            return None
    
    if detect_parking_query(user_message):
        from app.agents.memory_manager import get_persistent_memories
        try:
            memories = get_persistent_memories(user_id, limit=10)
            for mem in memories:
                if mem.get("topic") == "parking":
                    logger.info(f"[LLMChat] Parking DB read: user_id={user_id}, content={mem.get('content')}")
                    return f"รถของคุณจอดไว้ที่ {mem.get('content', 'ไม่ทราบ')}"
            
            logger.info(f"[LLMChat] Parking DB read no data: user_id={user_id}")
        except Exception as e:
            logger.error(f"[LLMChat] Parking DB read ERROR: {e}")
    
    logger.info(f"[LLMChat] Parking: no update/query detected, falling through")
    return None


def normalize_parking_location(location: str) -> str:
    """Normalize parking location to consistent format."""
    if not location:
        return location
    
    loc = location.strip().upper()
    
    loc = re.sub(r'^ชั้น\s*', '', loc)
    
    loc = re.sub(r'^FLOOR\s*', '', loc)
    
    return loc


def get_system_prompt() -> str:
    """Load the assistant chat system prompt."""
    prompt_path = os.path.join(
        os.path.dirname(__file__), 
        "..", 
        "prompts", 
        "assistant-chat.md"
    )
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return """คุณคือผู้ช่วยส่วนตัวที่ฉลาดและเป็นกันเอง ตอบเป็นภาษาไทยธรรมชาติ"""


def get_conversation_history(line_user_id: str) -> List[Dict[str, str]]:
    """Get conversation history for a user."""
    return _conversation_histories.get(line_user_id, [])


def add_to_history(line_user_id: str, role: str, content: str):
    """Add a message to user's conversation history."""
    if line_user_id not in _conversation_histories:
        _conversation_histories[line_user_id] = []
    
    _conversation_histories[line_user_id].append({
        "role": role,
        "content": content
    })
    
    # Keep only last MAX_HISTORY_TURNS * 2 (user + assistant)
    if len(_conversation_histories[line_user_id]) > MAX_HISTORY_TURNS * 2:
        _conversation_histories[line_user_id] = _conversation_histories[line_user_id][-MAX_HISTORY_TURNS*2:]


def clear_history(line_user_id: str):
    """Clear conversation history for a user."""
    if line_user_id in _conversation_histories:
        _conversation_histories[line_user_id] = []


def build_messages(
    user_message: str,
    line_user_id: str,
    user_name: str = "คุณ",
    user_role: str = "partner"
) -> List[Dict[str, str]]:
    """Build messages list including system prompt and conversation history."""
    messages = []
    
    # Add system prompt
    messages.append({
        "role": "system",
        "content": get_system_prompt()
    })
    
    # Add conversation history
    history = get_conversation_history(line_user_id)
    for msg in history:
        messages.append(msg)
    
    # Add current user message
    messages.append({
        "role": "user",
        "content": user_message
    })
    
    return messages


def generate_chat_response(
    user_message: str,
    line_user_id: str,
    user_name: str = "คุณ",
    user_role: str = "partner"
) -> str:
    """
    Generate a chat response using OpenAI API.
    
    This is used for Assistant Chat Mode when no command is detected.
    """
    logger.info(f"[LLMChat] generate_chat_response called with: {user_message[:30]}...")
    
    if not _settings.openai_api_key:
        logger.error("[LLMChat] No OpenAI API key configured")
        return "ขอโทษครับ ตอนนี้ระบบ AI ยังไม่พร้อม ลองใหม่อีกครั้งนะครับ"
    
    from app.repositories.user_repository import UserRepository
    user_repo = UserRepository()
    user_result = user_repo.get_by_line_user_id(line_user_id)
    user_id_str = None
    if user_result and user_result.data and len(user_result.data) > 0:
        user_id = user_result.data[0].get("id")
        if user_id:
            user_id_str = str(user_id)
    
    if user_id_str:
        parking_response = handle_parking_memory(line_user_id, user_message, user_id_str)
        if parking_response:
            add_to_history(line_user_id, "user", user_message)
            add_to_history(line_user_id, "assistant", parking_response)
            return parking_response
    
    # Build messages
    messages = build_messages(user_message, line_user_id, user_name, user_role)
    
    logger.info(f"[LLMChat] Using OpenAI API with model: {_settings.openai_model or 'gpt-4'}")
    
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {_settings.openai_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": _settings.openai_model or "gpt-4",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 500
    }
    
    try:
        logger.info(f"[LLMChat] Sending request to OpenAI...")
        response = httpx.post(url, json=payload, headers=headers, timeout=30)
        logger.info(f"[LLMChat] OpenAI response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            assistant_reply = data["choices"][0]["message"]["content"]
            
            # Add to history
            add_to_history(line_user_id, "user", user_message)
            add_to_history(line_user_id, "assistant", assistant_reply)
            
            logger.info(f"[LLMChat] OpenAI response received: {assistant_reply[:50]}...")
            return assistant_reply
        else:
            logger.error(f"[LLMChat] OpenAI error: {response.status_code} - {response.text}")
            return "ขอโทษครับ ตอนนี้ตอบไม่ได้ ลองใหม่อีกครั้งนะครับ"
    except Exception as e:
        logger.error(f"[LLMChat] OpenAI exception: {e}")
        return "ขอโทษครับ ตอนนี้มีปัญหา ลองใหม่อีกครั้งนะครับ"
