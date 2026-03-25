import json
import re
from typing import Optional
from app.services.llm_service import generate_json

CALENDAR_KEYWORDS = [
    "พรุ่งนี้", "วันนี้", "วันพรุ่ง", "ประชุม", "นัด", "ตาราง", 
    "กำหนดการ", "เวลา", "วันที่", "calendar", "meeting", 
    "schedule", "appointment", "วันจันทร์", "วันอังคาร", 
    "วันพุธ", "วันพฤหัส", "วันศุกร์", "วันเสาร์", "วันอาทิตย์",
    "เดือน", "ปี", "ครั้งที่", "ตอนเช้า", "ตอนบ่าย", "ตอนเย็น"
]

WORK_REQUEST_KEYWORDS = [
    "ช่วย", "ทำให้", "จัดให้", "สร้างให้", "เขียนให้", 
    "ช่วยทำ", "ขอให้", "รบกวน", "ช่วยหน่อย", "ทำให้หน่อย",
    "จัดให้หน่อย", "สร้างให้หน่อย", "สร้าง", "ช่วยสร้าง", "ให้หน่อย",
    "ซื้อให้", "หามาให้", "หาของให้"
]

REMINDER_KEYWORDS = ["เตือน", "reminder", "แจ้งเตือน"]

TASK_KEYWORDS = ["งาน", "ทำ", "task", "todo", "ลิสต์", "รายการ", "ซื้อของ", "จด", "ต้องทำ"]

PANTRY_KEYWORDS = ["ซื้อ", "ตู้เย็น", "ของในบ้าน", "หมดอายุ", "อาหาร", "วัตถุดิบ", "ของกิน", "ของในครัว"]

SEARCH_KEYWORDS = ["หา", "ค้น", "search", "google", "วิธี", "วิธีการ", "ข้อมูล"]

VALID_INTENTS = ["task", "pantry", "reminder", "calendar", "search", "work_request", "general_chat"]


def _apply_fallback_rules(text: str, result: dict) -> dict:
    """
    Post-processing layer to catch misclassifications.
    Priority: work_request > reminder > search > task > pantry > calendar > general_chat
    """
    normalized = text.lower().strip()
    
    # Priority 1: If contains work request keywords → override to work_request
    for keyword in WORK_REQUEST_KEYWORDS:
        if keyword.lower() in normalized:
            result["request_type"] = "work_request"
            result["confidence"] = min(result.get("confidence", 0.5) + 0.3, 1.0)
            result["reason"] = f"Override: detected work_request keyword '{keyword}'"
            return result
    
    # Priority 2: If contains reminder keywords → override to reminder (not calendar!)
    for keyword in REMINDER_KEYWORDS:
        if keyword.lower() in normalized:
            result["request_type"] = "reminder"
            result["confidence"] = min(result.get("confidence", 0.5) + 0.3, 1.0)
            result["reason"] = f"Override: detected reminder keyword '{keyword}'"
            return result
    
    # Priority 3: If contains search keywords → override to search
    for keyword in SEARCH_KEYWORDS:
        if keyword.lower() in normalized:
            result["request_type"] = "search"
            result["confidence"] = min(result.get("confidence", 0.5) + 0.3, 1.0)
            result["reason"] = f"Override: detected search keyword '{keyword}'"
            return result
    
    # Priority 4: If contains task keywords → override to task (check before calendar)
    has_task_action = any(kw in normalized for kw in TASK_KEYWORDS)
    if has_task_action:
        result["request_type"] = "task"
        result["confidence"] = min(result.get("confidence", 0.5) + 0.3, 1.0)
        result["reason"] = "Override: detected task keyword"
        return result
    
    # Priority 5: If contains pantry keywords → override to pantry (not work_request)
    has_work_intent = "ให้" in normalized
    for keyword in PANTRY_KEYWORDS:
        if keyword.lower() in normalized and not has_work_intent:
            result["request_type"] = "pantry"
            result["confidence"] = min(result.get("confidence", 0.5) + 0.3, 1.0)
            result["reason"] = f"Override: detected pantry keyword '{keyword}'"
            return result
    
    # Priority 6: If classified as general_chat but contains calendar keywords → override to calendar
    if result.get("request_type") == "general_chat":
        for keyword in CALENDAR_KEYWORDS:
            if keyword.lower() in normalized:
                result["request_type"] = "calendar"
                result["confidence"] = min(result.get("confidence", 0.5) + 0.3, 1.0)
                result["reason"] = f"Override: detected calendar keyword '{keyword}'"
                break
    
    return result


def _parse_llm_output(content: str) -> Optional[dict]:
    """
    Parse LLM output and extract valid JSON.
    Handles various formats and extraction methods.
    """
    try:
        # Try direct JSON parse
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    
    # Try to extract JSON from markdown code block
    json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Try to extract JSON from any code block
    json_match = re.search(r'```\s*(.*?)\s*```', content, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Try to find JSON-like object in the text
    json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
    
    return None


def _validate_result(result: dict) -> bool:
    """
    Validate that the result has required fields and valid values.
    """
    if not isinstance(result, dict):
        return False
    
    required_fields = ["request_type", "needs_clarification", "confidence"]
    for field in required_fields:
        if field not in result:
            return False
    
    if result.get("request_type") not in VALID_INTENTS:
        return False
    
    if not isinstance(result.get("needs_clarification"), bool):
        return False
    
    confidence = result.get("confidence", 0)
    if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 1):
        return False
    
    return True


def plan_with_intent(
    text: str,
    user_id: Optional[str] = None,
    line_user_id: Optional[str] = None,
    user_role: str = "partner",
    max_retries: int = 2
) -> dict:
    """
    Main function to classify intent using LLM + fallback rules.
    
    Args:
        text: User message
        user_id: Internal user UUID from Supabase
        line_user_id: LINE user ID
        user_role: 'owner' or 'partner'
        max_retries: Number of LLM retries
    
    Returns:
        dict with keys: request_type, needs_clarification, clarification_question,
                       can_answer_directly, confidence, reason, collected_fields
    """
    context = {
        "user_id": user_id,
        "line_user_id": line_user_id,
        "user_role": user_role
    }
    
    # Try to get LLM response
    result = None
    
    for attempt in range(max_retries):
        # Try using generate_json with planner prompt
        llm_result = _call_llm(text, context)
        
        if llm_result and _validate_result(llm_result):
            result = llm_result
            break
    
    # If all retries failed or no valid result, use rule-based fallback
    if result is None or not _validate_result(result):
        result = _rule_based_classification(text)
    
    # Apply fallback rules to catch any remaining misclassifications
    result = _apply_fallback_rules(text, result)
    
    # Ensure all required fields exist
    result = _ensure_required_fields(result)
    
    # Add collected fields for follow-up handling
    if "collected_fields" not in result:
        result["collected_fields"] = {}
    
    return result


def _call_llm(text: str, context: Optional[dict] = None) -> Optional[dict]:
    """
    Call LLM with the planner prompt.
    """
    try:
        from app.services.llm_service import generate_json as generate_json_llm
        
        # Read the planner prompt
        import os
        prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "planner-agent.md")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                system_prompt = f.read()
        except FileNotFoundError:
            system_prompt = _get_default_prompt()
        
        # Add user context to prompt if available
        if context and context.get("user_id"):
            system_prompt += f"\n\nCurrent user ID: {context['user_id']}"
            system_prompt += f"\nUser role: {context.get('user_role', 'partner')}"
        
        result = generate_json_llm(system_prompt, text)
        
        if result and _validate_result(result):
            return result
    except Exception:
        pass
    
    return None


def _rule_based_classification(text: str) -> dict:
    """
    Rule-based fallback classification.
    Uses keyword matching when LLM fails.
    Priority: work_request > reminder > search > task > pantry > calendar > general_chat
    """
    normalized = text.lower().strip()
    
    # Priority 1: Check work request keywords (highest - "ช่วยทำ", "สร้างให้", etc.)
    for keyword in WORK_REQUEST_KEYWORDS:
        if keyword.lower() in normalized:
            return {
                "request_type": "work_request",
                "needs_clarification": True,
                "clarification_question": "ต้องการให้ช่วยทำอะไรให้บ้างครับ?",
                "can_answer_directly": False,
                "confidence": 0.9,
                "reason": "Rule-based: detected work_request keyword"
            }
    
    # Priority 2: Check reminder keywords (before calendar - "เตือน" is explicit)
    for keyword in REMINDER_KEYWORDS:
        if keyword.lower() in normalized:
            return {
                "request_type": "reminder",
                "needs_clarification": True,
                "clarification_question": "ต้องการเตือนอะไร และเมื่อไหร่ครับ?",
                "can_answer_directly": False,
                "confidence": 0.9,
                "reason": "Rule-based: detected reminder keyword"
            }
    
    # Priority 3: Check search keywords (before task - "วิธี" is search)
    for keyword in SEARCH_KEYWORDS:
        if keyword.lower() in normalized:
            return {
                "request_type": "search",
                "needs_clarification": True,
                "clarification_question": "ต้องการหาข้อมูลเรื่องอะไรครับ?",
                "can_answer_directly": False,
                "confidence": 0.8,
                "reason": "Rule-based: detected search keyword"
            }
    
    # Priority 4: Check task keywords (check before calendar)
    has_task_action = any(kw in normalized for kw in TASK_KEYWORDS)
    if has_task_action:
        return {
            "request_type": "task",
            "needs_clarification": False,
            "clarification_question": None,
            "can_answer_directly": True,
            "confidence": 0.8,
            "reason": "Rule-based: detected task keyword"
        }
    
    # Priority 5: Check pantry keywords (but not if "ให้" is present - that's work_request)
    has_work_intent = "ให้" in normalized
    for keyword in PANTRY_KEYWORDS:
        if keyword.lower() in normalized and not has_work_intent:
            return {
                "request_type": "pantry",
                "needs_clarification": False,
                "clarification_question": None,
                "can_answer_directly": True,
                "confidence": 0.8,
                "reason": "Rule-based: detected pantry keyword"
            }
    
    # Priority 6: Check calendar keywords
    for keyword in CALENDAR_KEYWORDS:
        if keyword.lower() in normalized:
            return {
                "request_type": "calendar",
                "needs_clarification": False,
                "clarification_question": None,
                "can_answer_directly": True,
                "confidence": 0.9,
                "reason": "Rule-based: detected calendar keyword"
            }
    
    # Default to general_chat for greetings/farewells
    greetings = ["สวัสดี", "hello", "hi", "ดี", "good morning", "good evening", "good night"]
    farewells = ["ลาก่อน", "bye", "再见", "goodbye"]
    
    for greeting in greetings:
        if greeting.lower() in normalized:
            return {
                "request_type": "general_chat",
                "needs_clarification": False,
                "clarification_question": None,
                "can_answer_directly": True,
                "confidence": 0.9,
                "reason": "Rule-based: detected greeting"
            }
    
    for farewell in farewells:
        if farewell.lower() in normalized:
            return {
                "request_type": "general_chat",
                "needs_clarification": False,
                "clarification_question": None,
                "can_answer_directly": True,
                "confidence": 0.9,
                "reason": "Rule-based: detected farewell"
            }
    
    # Unknown - default to general_chat with clarification
    return {
        "request_type": "general_chat",
        "needs_clarification": True,
        "clarification_question": "ขอรายละเอียดเพิ่มอีกนิดนะครับ จะได้ช่วยได้ตรงจุด",
        "can_answer_directly": False,
        "confidence": 0.3,
        "reason": "Rule-based: no keywords matched"
    }


def _ensure_required_fields(result: dict) -> dict:
    """
    Ensure all required fields exist with valid defaults.
    """
    defaults = {
        "clarification_question": None,
        "can_answer_directly": False,
        "reason": ""
    }
    
    for key, default_value in defaults.items():
        if key not in result:
            result[key] = default_value
    
    # Ensure confidence is valid
    if "confidence" not in result:
        result["confidence"] = 0.5
    else:
        result["confidence"] = max(0.0, min(1.0, float(result["confidence"])))
    
    # Ensure request_type is valid
    if result.get("request_type") not in VALID_INTENTS:
        result["request_type"] = "general_chat"
    
    # Ensure needs_clarification is bool
    result["needs_clarification"] = bool(result.get("needs_clarification", False))
    
    return result


def _get_default_prompt() -> str:
    """
    Get default system prompt if file not found.
    """
    return """You are a planning engine. Your ONLY job is to analyze user requests and output JSON.

STRICT RULES:
1. ALWAYS output valid JSON
2. NEVER include explanation outside JSON
3. NEVER say "done" or "completed"

OUTPUT STRUCTURE:
{
  "request_type": "task|pantry|reminder|calendar|search|work_request|general_chat",
  "needs_clarification": true or false,
  "clarification_question": "question in Thai or null",
  "can_answer_directly": true or false,
  "confidence": 0.0-1.0,
  "reason": "explanation in Thai"
}

If unclear, ask clarification in Thai."""


# Keep backward compatibility
def plan_work_request(text: str) -> dict:
    """
    Legacy function for work request planning.
    Now delegates to plan_with_intent.
    """
    return plan_with_intent(text)
