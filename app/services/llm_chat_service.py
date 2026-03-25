"""
LLM Chat Service for Assistant Chat Mode.
Provides natural conversation when no command is detected.
"""
import os
import httpx
from typing import Optional, List, Dict, Any
from app.config import Settings

_settings = Settings()

# In-memory conversation history per user
# Format: {line_user_id: [{"role": "user"/"assistant", "content": "..."}]}
_conversation_histories: Dict[str, List[Dict[str, str]]] = {}

# Max turns to keep in history
MAX_HISTORY_TURNS = 4


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
    
    # Add user context as first message if available
    if user_name and user_name != "คุณ":
        context_note = f"(Context: คุณกำลังคุยกับ {user_name})"
        # We can add this as a system message or include in first user message
    
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
    Generate a chat response using LLM.
    
    This is used for Assistant Chat Mode when no command is detected.
    Supports both standard OpenAI and Azure OpenAI.
    """
    if not _settings.openai_api_key:
        return "ขอโทษครับ ตอนนี้ระบบ AI ยังไม่พร้อม ลองใหม่อีกครั้งนะครับ"
    
    # Build messages
    messages = build_messages(user_message, line_user_id, user_name, user_role)
    
    # Check if using Azure OpenAI
    if _settings.llm_provider == "azure" and _settings.azure_openai_endpoint:
        return _generate_azure_response(messages, line_user_id, user_message)
    else:
        return _generate_openai_response(messages, line_user_id, user_message)


def _generate_openai_response(
    messages: List[Dict[str, str]],
    line_user_id: str,
    user_message: str
) -> str:
    """Generate response using standard OpenAI API."""
    import logging
    logger = logging.getLogger(__name__)
    
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
        response = httpx.post(url, json=payload, headers=headers, timeout=30)
        logger.info(f"[LLMChat] OpenAI response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            assistant_reply = data["choices"][0]["message"]["content"]
            
            # Add to history
            add_to_history(line_user_id, "user", user_message)
            add_to_history(line_user_id, "assistant", assistant_reply)
            
            logger.info(f"[LLMChat] OpenAI response: {assistant_reply[:50]}...")
            return assistant_reply
        else:
            logger.error(f"[LLMChat] OpenAI error: {response.text}")
            return "ขอโทษครับ ตอนนี้ตอบไม่ได้ ลองใหม่อีกครั้งนะครับ"
    except Exception as e:
        logger.error(f"[LLMChat] OpenAI error: {e}")
        return "ขอโทษครับ ตอนนี้มีปัญหา ลองใหม่อีกครั้งนะครับ"


def _generate_azure_response(
    messages: List[Dict[str, str]],
    line_user_id: str,
    user_message: str
) -> str:
    """Generate response using Azure OpenAI API."""
    import logging
    logger = logging.getLogger(__name__)
    
    # Azure OpenAI endpoint format:
    # https://{resource}.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version={version}
    endpoint = _settings.azure_openai_endpoint.rstrip("/")
    deployment = _settings.azure_openai_deployment
    api_version = _settings.azure_openai_api_version or "2024-02-15-preview"
    
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    
    headers = {
        "api-key": _settings.openai_api_key,
        "Content-Type": "application/json"
    }
    
    payload = {
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 500
    }
    
    logger.info(f"[LLMChat] Using Azure OpenAI: {endpoint}")
    
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=30)
        logger.info(f"[LLMChat] Azure response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            assistant_reply = data["choices"][0]["message"]["content"]
            
            # Add to history
            add_to_history(line_user_id, "user", user_message)
            add_to_history(line_user_id, "assistant", assistant_reply)
            
            logger.info(f"[LLMChat] Azure response: {assistant_reply[:50]}...")
            return assistant_reply
        else:
            logger.error(f"[LLMChat] Azure error: {response.status_code} - {response.text}")
            return "ขอโทษครับ ตอนนี้ตอบไม่ได้ ลองใหม่อีกครั้งนะครับ"
    except Exception as e:
        logger.error(f"[LLMChat] Azure error: {e}")
        return "ขอโทษครับ ตอนนี้มีปัญหา ลองใหม่อีกครั้งนะครับ"
