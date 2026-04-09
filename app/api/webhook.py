"""
LINE Webhook handler with dual-mode architecture:
- Agent Action Mode: deterministic commands (add_task, list_tasks, reminder, etc.)
- Assistant Chat Mode: natural conversation when no command detected
"""
import logging
import time
import uuid
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

# ============================================================
# PART 2: WEBHOOK IDEMPOTENCY FIX
# In-memory cache for processed webhook events
# ============================================================

_processed_events: dict[str, float] = {}
DEDUP_TTL_SECONDS = 300  # 5 minutes TTL


def _is_event_processed(event_id: str) -> bool:
    """Check if event has already been processed."""
    if event_id in _processed_events:
        timestamp = _processed_events[event_id]
        if time.time() - timestamp < DEDUP_TTL_SECONDS:
            logger.info(f"[WebhookDedup] event_id={event_id} already_processed=True")
            return True
        else:
            del _processed_events[event_id]
    return False


def _mark_event_processed(event_id: str):
    """Mark event as processed."""
    _processed_events[event_id] = time.time()
    logger.info(f"[WebhookDedup] event_id={event_id} marked_processed=True")


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


async def handle_pending_action(
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
    from app.agents.memory_manager import get_session, classify_reminder_followup, has_strong_new_intent, clear_session
    
    session = get_session(line_user_id)
    pending_action = session.pending_action
    retry_count = session.pending_retry_count
    
    if not pending_action:
        return None, False
    
    existing_collected = session.collected_fields or {}
    
    logger.info(f"[PendingActionFix] ===== PENDING ACTION DETECTED =====")
    logger.info(f"[PendingActionFix] pending_action={pending_action}")
    logger.info(f"[PendingActionFix] existing_collected={existing_collected}")
    logger.info(f"[PendingActionFix] user_message={user_message}")
    logger.info(f"[PendingActionFix] retry_count={retry_count}")
    
    branch_entered = pending_action
    merged_fields_initialized = False
    merged_fields = {}
    rerouted = False
    
    if pending_action == "clarify_intent":
        logger.info(f"[PendingActionFix] branch_entered=clarify_intent")
        
        if has_strong_new_intent(user_message):
            logger.info(f"[PendingActionFix] new_intent_detected=true in clarify_intent")
            clear_session(line_user_id)
            rerouted = True
            logger.info(f"[PendingActionFix] rerouted=True, returning None for fresh detection")
            return None, False
        
        clarification_question = existing_collected.get("clarification_question", "ขอความชัดเจนได้ไหมครับ?")
        logger.info(f"[PendingActionFix] clarification_question={clarification_question}")
        
        merged_fields = existing_collected.copy()
        merged_fields["user_replied"] = user_message
        merged_fields_initialized = True
        
        logger.info(f"[PendingActionFix] merged_fields_initialized={merged_fields_initialized}")
        logger.info(f"[PendingActionFix] branch_result_action=clarify_intent_continue")
        
        from app.services.response_handler import get_response_for_action
        response, is_complete = await get_response_for_action(
            action="clarify_intent",
            extracted_fields=merged_fields,
            user_id=user_id,
            line_user_id=line_user_id,
            user_role=user_role
        )
        
        logger.info(f"[PendingActionFix] clarify_intent_response={str(response)[:50] if response else 'None'}")
        logger.info(f"[PendingActionFix] is_complete={is_complete}")
        
        if is_complete:
            clear_session(line_user_id)
            logger.info(f"[PendingActionFix] session_cleared=True")
        else:
            from app.agents.memory_manager import update_session
            update_session(
                line_user_id,
                pending_action=pending_action,
                needs_clarification=True,
                user_message=user_message,
                collected_fields=merged_fields
            )
            logger.info(f"[PendingActionFix] session_updated=clarify_intent")
        
        logger.info(f"[PendingActionFix] safe_return=True")
        return response, is_complete
    
    elif pending_action == "create_reminder":
        logger.info(f"[PendingActionFix] branch_entered=create_reminder")
        
        classification = classify_reminder_followup(user_message)
        logger.info(f"[PendingActionFix] classification={classification}")
        
        MAX_RETRIES = 2
        
        if classification == "explicit_cancel":
            clear_session(line_user_id)
            logger.info(f"[PendingActionFix] reminder_cancelled=True")
            return "ได้ครับ ยกเลิกการตั้งเตือนให้แล้ว", True
        
        if classification == "frustration" or classification == "topic_change":
            # If it's a strong new secretary intent, break out and process as new command
            if has_strong_new_intent(user_message):
                logger.info(f"[PendingActionFix] new_intent_detected=true, clearing old session")
                clear_session(line_user_id)
                return None, False
            
            # [NEW] If it's a topic change (e.g., general question), clear session and 
            # let it fall through to LLM Chat Mode in the main loop.
            if classification == "topic_change":
                logger.info(f"[PendingActionFix] topic_change detected, clearing session for LLM Chat")
                clear_session(line_user_id)
                return None, False
            
            if retry_count >= MAX_RETRIES:
                clear_session(line_user_id)
                logger.info(f"[PendingActionFix] max_retries_exceeded=True")
                return "ขอโทษครับ ผมเข้าใจแล้ว ถ้าต้องการตั้งเตือนใหม่ พิมพ์มาได้เลยนะครับ", True
            else:
                session.increment_retry()
                return "ขอโทษครับ ยังไม่เห็นเวลาแจ้งเตือน ถ้าต้องการยกเลิกพิมพ์ 'ยกเลิก' ได้ครับ", False
        
        if classification == "invalid_time_reply":
            if retry_count >= MAX_RETRIES:
                clear_session(line_user_id)
                logger.info(f"[PendingActionFix] max_retries_exceeded_invalid=True")
                return "ผมยกเลิกการตั้งเตือนให้ก่อนนะครับ ถ้าต้องการตั้งใหม่ พิมพ์มาได้เลย", True
            else:
                session.increment_retry()
                return "ยังไม่เห็นเวลาแจ้งเตือนครับ ถ้าต้องการยกเลิกพิมพ์ 'ยกเลิก' ได้", False
        
        from app.services.line_service import (
            verify_signature, 
            reply_message, 
            push_message, 
            reply_flex_message, 
            push_flex_message
        )
        
        existing = session.collected_fields or {}
        original_message = existing.get("message", "")
        existing_date = existing.get("date", "today")
        existing_time = existing.get("time")
        
        logger.info(f"[PendingActionFix] initial_message={original_message}")
        logger.info(f"[PendingActionFix] initial_parsed_date={existing_date}")
        
        from app.services.reminder_service import reminder_service
        parsed = reminder_service.parse_reminder_message(user_message)
        
        logger.info(f"[PendingActionFix] followup_parsed_date={parsed.get('date')}")
        logger.info(f"[PendingActionFix] followup_parsed_time={parsed.get('time')}")
        
        has_existing_message = bool(original_message and len(original_message) >= 3)
        has_new_message = bool(parsed.get("message", "").strip())
        
        if has_existing_message:
            final_message = original_message
        elif has_new_message and parsed.get("message") not in ["ฉัน", "พรุ่งนี้"]:
            final_message = parsed.get("message", "").strip()
        else:
            final_message = ""
        
        parsed_date = parsed.get("date", "today")
        parsed_time = parsed.get("time")
        
        explicit_date_patterns = [
            "พรุ่งนี้", "วันพรุ่ง", "มะรืนนี้", "มะรืน", "วันนี้",
            "วันจันทร์", "วันอังคาร", "วันพุธ", "วันพฤหัสบดี", "วันศุกร์", "วันเสาร์", "วันอังคาร",
            "วันจันทร์หน้า", "วันอังคารหน้า", "วันพุธหน้า", "วันพฤหัสหน้า", "วันศุกร์หน้า"
        ]
        msg_lower = user_message.lower()
        has_explicit_new_date = any(pattern in msg_lower for pattern in explicit_date_patterns)
        
        if has_explicit_new_date:
            final_date = parsed_date
        elif existing_date and existing_date != "today" and parsed_time:
            final_date = existing_date
        elif existing_date and existing_date != "today":
            final_date = existing_date
        else:
            final_date = parsed_date or existing.get("date", "today")
        
        final_time = parsed_time or existing_time
        
        if parsed_time:
            final_time = parsed_time
        elif existing_time:
            final_time = existing_time
        
        final_has_time = parsed.get("has_time", False) or existing.get("has_time", False) or final_time is not None
        
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
        merged_fields_initialized = True
        
        logger.info(f"[PendingActionFix] merged_fields_initialized={merged_fields_initialized}")
        logger.info(f"[PendingActionFix] final_message={final_message}")
        logger.info(f"[PendingActionFix] final_date={final_date}")
        logger.info(f"[PendingActionFix] final_time={final_time}")
    
    elif pending_action == "add_task":
        logger.info(f"[PendingActionFix] branch_entered=add_task")
        merged_fields = existing_collected.copy()
        merged_fields["title"] = user_message.strip()
        merged_fields_initialized = True
        logger.info(f"[PendingActionFix] task_title={merged_fields['title']}")
    
    elif pending_action == "add_pantry":
        logger.info(f"[PendingActionFix] branch_entered=add_pantry")
        merged_fields = existing_collected.copy()
        merged_fields["item_name"] = user_message.strip()
        merged_fields_initialized = True
        logger.info(f"[PendingActionFix] item_name={merged_fields['item_name']}")
    
    elif pending_action == "cancel_reminder":
        logger.info(f"[PendingActionFix] branch_entered=cancel_reminder")
        merged_fields = existing_collected.copy()
        merged_fields["user_replied"] = user_message.strip()
        merged_fields_initialized = True
        logger.info(f"[PendingActionFix] reply={merged_fields['user_replied']}")
    
    else:
        logger.warning(f"[PendingActionFix] unknown_pending_action={pending_action}, clearing session")
        clear_session(line_user_id)
        return "ขอโทษครับ มีปัญหากับระบบ ลองใหม่อีกครั้งนะครับ", True
    
    logger.info(f"[PendingActionFix] merged_fields={merged_fields}")
    logger.info(f"[PendingActionFix] branch_entered={branch_entered}")
    
    from app.services.response_handler import get_response_for_action
    response, is_complete = await get_response_for_action(
        action=pending_action,
        extracted_fields=merged_fields,
        user_id=user_id,
        line_user_id=line_user_id,
        user_role=user_role
    )
    
    logger.info(f"[PendingActionFix] response={str(response)[:50] if response else 'None'}")
    logger.info(f"[PendingActionFix] is_complete={is_complete}")
    
    if is_complete:
        clear_session(line_user_id)
        logger.info(f"[PendingActionFix] action_complete_session_cleared=True")
    else:
        from app.agents.memory_manager import update_session
        update_session(
            line_user_id,
            pending_action=pending_action,
            needs_clarification=True,
            user_message=user_message,
            collected_fields=merged_fields
        )
        logger.info(f"[PendingActionFix] session_updated_for_continue=True")
    
    logger.info(f"[PendingActionFix] safe_return=True")
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
            # ============================================================
            # PART 2 FIX: Idempotency check - use event_id for deduplication
            # ============================================================
            event_id = event.get("eventId") or event.get("replyToken") or f"{event.get('source', {}).get('userId')}_{event.get('message', {}).get('id')}"
            
            logger.info(f"[WebhookFlow] start_processing event_id={event_id}")
            
            if _is_event_processed(event_id):
                logger.info(f"[WebhookFlow] skipped_duplicate event_id={event_id}")
                continue
            
            _mark_event_processed(event_id)
            
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
            pending_response, _ = await handle_pending_action(line_user_id, user_message, user_id, user_role)
            
            if pending_response:
                response_text = pending_response
                logger.info(f"[Webhook] Using pending action response: {str(response_text)[:50]}")
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
                    
                    response_text, is_complete = await get_response_for_action(
                        action=action,
                        extracted_fields=extracted_fields,
                        user_id=user_id,
                        line_user_id=line_user_id,
                        user_role=user_role
                    )
                    
                    # session management: update if not complete
                    if is_complete:
                        clear_session(line_user_id)
                        logger.info(f"[Webhook] Complete - session cleared")
                    else:
                        # If not complete (waiting for confirmation or follow-up), set as pending
                        update_session(
                            line_user_id,
                            pending_action=action,
                            needs_clarification=True, # Mark that we need follow-up
                            user_message=user_message,
                            collected_fields=extracted_fields
                        )
                        logger.info(f"[Webhook] Pending - session updated with action: {action}")
                    
                    logger.info(f"[Webhook] Response: {str(response_text)[:50] if response_text else 'None'}...")
                    
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
                        
                        if not response_text:
                            logger.error(f"[Webhook] Chat returned empty response")
                            response_text = "มีอะไรให้ช่วยไหมครับ?"
                        
                        logger.info(f"[Webhook] Chat response: {response_text[:80]}...")
                    except Exception as e:
                        logger.error(f"[Webhook] Chat generation error: {e}", exc_info=True)
                        response_text = "ขอโทษครับ ตอนนี้ระบบมีปัญหา ลองใหม่อีกครั้งนะครับ"
            
            if not response_text:
                response_text = FALLBACK_RESPONSE
            
            logger.info(f"[WebhookFlow] sending_reply event_id={event_id}")
            
            if response_text:
                if isinstance(response_text, dict):
                    # Send Flex Message
                    line_service.reply_flex_message(reply_token, "ผู้ช่วยส่วนตัวของคุณ", response_text)
                else:
                    # Send Text Message
                    line_service.reply_message(reply_token, response_text)
                
                logger.info(f"[WebhookFlow] reply_sent event_id={event_id}")
                logger.info(f"[Webhook] Reply sent: {str(response_text)[:50]}...")
            else:
                logger.warning(f"[Webhook] Failed to send reply for: {user_message}")
    
    return {"status": "ok"}
