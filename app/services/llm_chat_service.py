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
    r"จอดรถชั้น\s*(\S+)",
    r"จอดรถ\s*ชั้น\s*(\S+)",
    r"จอดรถ\s*(.+)$",
    r"parking\s*(.+)$",
    r"จอด\s*(.+)$",
]

PARKING_QUERY_PATTERNS = [
    r"จอดรถไว้ตรงไหน",
    r"รถจอดไว้ที่ไหน",
    r"รถอยู่ไหน",
    r"จอดรถที่ไหน",
    r"where\s*parking",
]


def detect_parking_update(message: str) -> Optional[str]:
    """Detect if message is a parking location update."""
    for pattern in PARKING_UPDATE_PATTERNS:
        match = re.search(pattern, message.lower())
        if match:
            location = match.group(1).strip()
            if location and len(location) < 20:
                logger.info(f"[LLMChat] Parking update detected: {location}")
                return location
    return None


def detect_parking_query(message: str) -> bool:
    """Detect if message is a query about parking location."""
    return any(re.search(p, message.lower()) for p in PARKING_QUERY_PATTERNS)


def handle_parking_memory(line_user_id: str, user_message: str, user_id: str) -> Optional[str]:
    """Handle parking memory: save updates, answer queries from DB."""
    update_location = detect_parking_update(user_message)
    
    if update_location:
        from app.agents.memory_manager import add_persistent_memory
        try:
            add_persistent_memory(user_id, "parking", f"จอดรถที่ชั้น {update_location}")
            logger.info(f"[LLMChat] Parking memory saved: user_id={user_id}, location={update_location}")
        except Exception as e:
            logger.error(f"[LLMChat] Failed to save parking memory: {e}")
        return None
    
    if detect_parking_query(user_message):
        from app.agents.memory_manager import get_persistent_memories
        try:
            memories = get_persistent_memories(user_id, limit=10)
            for mem in memories:
                if mem.get("topic") == "parking":
                    logger.info(f"[LLMChat] Parking memory read from DB: {mem.get('content')}")
                    return f"รถของคุณจอดไว้ที่ {mem.get('content', 'ไม่ทราบ')}"
            
            logger.info(f"[LLMChat] No parking memory in DB for user_id={user_id}")
        except Exception as e:
            logger.error(f"[LLMChat] Failed to read parking memory: {e}")
    
    return None


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
