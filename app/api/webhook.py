"""
LINE Webhook handler with dual-mode architecture:
- Agent Action Mode: deterministic commands (add_task, list_tasks, reminder, etc.)
- Assistant Chat Mode: natural conversation when no command detected
"""
import logging
from fastapi import APIRouter, Request, HTTPException, Header
from app.services import line_service
from app.services.response_handler import get_response_for_action, get_response_for_intent, FALLBACK_RESPONSE
from app.services.llm_chat_service import generate_chat_response
from app.agents.planner_agent import plan_with_intent
from app.agents.command_detector import detect_command
from app.agents.memory_manager import update_session, get_session_context, clear_session
from app.repositories.user_repository import UserRepository
from app.services.response_handler import get_user_display_name

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

user_repo = UserRepository()


def get_or_create_user(line_user_id: str) -> dict:
    """Get user by LINE user ID or create if not exists."""
    try:
        result = user_repo.get_by_line_user_id(line_user_id)
        if result.data and len(result.data) > 0:
            return result.data[0]
        
        created = user_repo.create(line_user_id=line_user_id)
        if created.data and len(created.data) > 0:
            return created.data[0]
        
        return {"id": None, "line_user_id": line_user_id, "role": "partner"}
    except Exception as e:
        logger.error(f"[Webhook] Error getting/creating user: {e}")
        return {"id": None, "line_user_id": line_user_id, "role": "partner"}


def handle_pending_action(
    line_user_id: str,
    user_message: str,
    user_id: str,
    user_role: str
) -> tuple[str, bool]:
    """
    Handle follow-up messages when there's a pending action.
    
    Returns:
        (response_text, is_complete)
    """
    session = get_session_context(line_user_id)
    pending_action = session.get("pending_action")
    
    if not pending_action:
        return None, False
    
    logger.info(f"[Webhook] ===== PENDING ACTION DETECTED =====")
    logger.info(f"[Webhook] pending_action: {pending_action}")
    logger.info(f"[Webhook] Session collected_fields: {session.get('collected_fields')}")
    logger.info(f"[Webhook] User message: {user_message}")
    
    # CRITICAL: Start with FRESH fields, do NOT merge old data incorrectly
    merged_fields = {}
    
    if pending_action == "create_reminder":
        from app.services.reminder_service import reminder_service
        
        existing = session.get("collected_fields", {})
        original_message = existing.get("message", "")
        
        logger.info(f"[Webhook] Original message from session: '{original_message}'")
        
        parsed = reminder_service.parse_reminder_message(user_message)
        
        logger.info(f"[Webhook] Parsed from new message: {parsed}")
        logger.info(f"[Webhook] Existing collected: {existing}")
        
        has_existing_message = bool(original_message and len(original_message) >= 3)
        has_new_message = bool(parsed.get("message", "").strip())
        
        logger.info(f"[Webhook] has_existing_message={has_existing_message}, has_new_message={has_new_message}")
        
        if has_existing_message:
            final_message = original_message
            logger.info(f"[Webhook] Preserving original message: '{final_message}'")
        elif has_new_message and parsed.get("message") not in ["ฉัน", "พรุ่งนี้"]:
            final_message = parsed.get("message", "").strip()
            logger.info(f"[Webhook] Using new message: '{final_message}'")
        else:
            final_message = ""
            logger.info(f"[Webhook] No valid message, will need clarification")
        
        final_time = parsed.get("time") or existing.get("time")
        final_date = parsed.get("date") or existing.get("date")
        
        if parsed.get("time"):
            final_time = parsed.get("time")
        if parsed.get("date"):
            final_date = parsed.get("date")
        
        final_has_time = parsed.get("has_time", False) or existing.get("has_time", False) or final_time is not None
        
        logger.info(f"[Webhook] final_time={final_time}, final_date={final_date}, final_has_time={final_has_time}")
        
        remind_at = None
        if final_date and final_time:
            remind_at = reminder_service.calculate_remind_at(final_date, final_time)
        
        merged_fields = {
            "message": final_message,
            "date": final_date,
            "time": final_time,
            "has_time": final_has_time,
            "remind_at": remind_at
        }
        
        logger.info(f"[Webhook] Reminder merged: message='{final_message}', date={final_date}, time={final_time}, has_time={final_has_time}, remind_at={remind_at}")
        
    elif pending_action == "add_task":
        merged_fields["title"] = user_message.strip()
        logger.info(f"[Webhook] Task title: {merged_fields['title']}")
    
    elif pending_action == "add_pantry":
        merged_fields["item_name"] = user_message.strip()
        logger.info(f"[Webhook] Pantry item: {merged_fields['item_name']}")
    
    # Get response with merged fields
    from app.services.response_handler import get_response_for_action
    response, is_complete = get_response_for_action(
        action=pending_action,
        extracted_fields=merged_fields,
        user_id=user_id,
        line_user_id=line_user_id,
        user_role=user_role
    )
    
    logger.info(f"[Webhook] Response: {response[:100] if response else 'None'}...")
    logger.info(f"[Webhook] Is complete: {is_complete}")
    
    # Update session with new collected fields
    if is_complete:
        clear_session(line_user_id)
        logger.info(f"[Webhook] ===== ACTION COMPLETE, SESSION CLEARED =====")
    else:
        update_session(
            line_user_id,
            pending_action=pending_action,
            needs_clarification=True,
            user_message=user_message,
            collected_fields=merged_fields
        )
        logger.info(f"[Webhook] ===== PENDING, SESSION UPDATED =====")
    
    return response, is_complete


@router.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(None)
):
    body = await request.body()
    
    if not x_line_signature:
        raise HTTPException(status_code=401, detail="Missing signature")
    
    if not line_service.verify_signature(body, x_line_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    import json
    try:
        events = json.loads(body).get("events", [])
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    for event in events:
        if event.get("type") == "message" and event.get("message", {}).get("type") == "text":
            user_message = event["message"]["text"]
            reply_token = event["replyToken"]
            
            source = event.get("source", {})
            line_user_id = source.get("userId")
            
            if not line_user_id:
                logger.warning("[Webhook] No userId in event source")
                line_user_id = "unknown"
            
            user = get_or_create_user(line_user_id)
            user_id = user.get("id")
            user_role = user.get("role", "partner")
            
            logger.info(f"[Webhook] User: {line_user_id}, Message: {user_message}")
            
            # Step 1: Check for pending action (follow-up)
            pending_response, _ = handle_pending_action(line_user_id, user_message, user_id, user_role)
            
            if pending_response:
                response_text = pending_response
                logger.info(f"[Webhook] Using pending action response: {response_text[:50]}")
            else:
                # Step 2: Try explicit command detection
                command_result = detect_command(user_message)
                
                if command_result:
                    # Explicit command found - use it directly
                    action = command_result["action"]
                    extracted_fields = command_result["extracted_fields"]
                    needs_clarification = command_result["needs_clarification"]
                    
                    logger.info(f"[Webhook] ===== EXPLICIT COMMAND =====")
                    logger.info(f"[Webhook] Action: {action}")
                    logger.info(f"[Webhook] Fields: {extracted_fields}")
                    logger.info(f"[Webhook] Needs clarification: {needs_clarification}")
                    
                    response_text, is_complete = get_response_for_action(
                        action=action,
                        extracted_fields=extracted_fields,
                        user_id=user_id,
                        line_user_id=line_user_id,
                        user_role=user_role
                    )
                    
                    # CRITICAL: Only update session if needs clarification (not one-shot)
                    if is_complete:
                        clear_session(line_user_id)
                        logger.info(f"[Webhook] Complete - session cleared")
                    elif needs_clarification:
                        # Only set pending if we actually need more info
                        update_session(
                            line_user_id,
                            pending_action=action,
                            needs_clarification=True,
                            user_message=user_message,
                            collected_fields=extracted_fields
                        )
                        logger.info(f"[Webhook] Pending - session updated with action: {action}")
                    # else: one-shot complete but not saved - don't set pending
                    
                    logger.info(f"[Webhook] Response: {response_text[:50] if response_text else 'None'}...")
                    
                else:
                    # ===== DUAL MODE: Assistant Chat Mode =====
                    # No command detected → use LLM for natural conversation
                    logger.info(f"[Webhook] ===== ASSISTANT CHAT MODE =====")
                    logger.info(f"[Webhook] User: {line_user_id}, Message: {user_message}")
                    
                    # Get user name for context
                    user_name = get_user_display_name(line_user_id) if line_user_id else "คุณ"
                    logger.info(f"[Webhook] User name: {user_name}")
                    
                    # Generate natural chat response
                    try:
                        response_text = generate_chat_response(
                            user_message=user_message,
                            line_user_id=line_user_id,
                            user_name=user_name,
                            user_role=user_role
                        )
                        
                        if not response_text or "ขอโทษ" in response_text:
                            logger.error(f"[Webhook] Chat returned error/empty: {response_text}")
                            response_text = "มีอะไรให้ช่วยไหมครับ?"
                        
                        logger.info(f"[Webhook] Chat response: {response_text[:80]}...")
                    except Exception as e:
                        logger.error(f"[Webhook] Chat generation error: {e}", exc_info=True)
                        response_text = "ขอโทษครับ ตอนนี้ระบบมีปัญหา ลองใหม่อีกครั้งนะครับ"
            
            if not response_text:
                response_text = FALLBACK_RESPONSE
            
            success = line_service.reply_message(reply_token, response_text)
            
            if success:
                logger.info(f"[Webhook] Reply sent: {response_text[:50]}...")
            else:
                logger.warning(f"[Webhook] Failed to send reply for: {user_message}")
    
    return {"status": "ok"}
