import json
import httpx
import logging
from typing import Optional
from app.config import Settings

_settings = Settings()
logger = logging.getLogger(__name__)


def generate_response(system_prompt: str, user_input: str, temperature: float = 0.7) -> str:
    if not _settings.openai_api_key:
        return "ตอนนี้ระบบยังประมวลผลไม่ได้ ลองใหม่อีกครั้งนะครับ"
    
    logger.info(f"[LLMService] generate_response called with model: {_settings.openai_model or 'gpt-4'}")
    
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {_settings.openai_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": _settings.openai_model or "gpt-4",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ],
        "temperature": temperature
    }
    
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=30)
        logger.info(f"[LLMService] OpenAI response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            return data["choices"][0]["message"]["content"]
        
        logger.error(f"[LLMService] OpenAI error: {response.text}")
        return "ตอนนี้ระบบยังประมวลผลไม่ได้ ลองใหม่อีกครั้งนะครับ"
    except Exception as e:
        logger.error(f"[LLMService] Exception: {e}")
        return "ตอนนี้ระบบยังประมวลผลไม่ได้ ลองใหม่อีกครั้งนะครับ"


def generate_json(system_prompt: str, user_input: str) -> dict:
    if not _settings.openai_api_key:
        return {
            "request_type": "unknown",
            "needs_clarification": True,
            "clarification_question": "ขอรายละเอียดเพิ่มอีกนิดนะครับ เพื่อช่วยคุณได้ตรงจุดมากขึ้น",
            "can_answer_directly": False,
            "confidence": 0.0,
            "reason": "LLM not available"
        }
    
    logger.info(f"[LLMService] generate_json called with model: {_settings.openai_model or 'gpt-4'}")
    
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {_settings.openai_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": _settings.openai_model or "gpt-4",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ],
        "temperature": 0.2
    }
    
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=30)
        logger.info(f"[LLMService] OpenAI JSON response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            result = json.loads(content)
            if "request_type" in result and "needs_clarification" in result:
                return result
    except (json.JSONDecodeError, KeyError, Exception) as e:
        logger.error(f"[LLMService] JSON parse error: {e}")
    
    return {
        "request_type": "unknown",
        "needs_clarification": True,
        "clarification_question": "ขอรายละเอียดเพิ่มอีกนิดนะครับ เพื่อช่วยคุณได้ตรงจุดมากขึ้น",
        "can_answer_directly": False,
        "confidence": 0.0,
        "reason": "invalid response from LLM"
    }
