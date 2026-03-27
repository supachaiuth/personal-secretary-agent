"""
Memory manager for tracking user conversation context.
Supports follow-up handling and persistent context across messages.
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# In-memory storage for user sessions
# In production, this should be stored in Redis or database
_user_sessions: Dict[str, Dict[str, Any]] = {}

# Session timeout in minutes
SESSION_TIMEOUT = 10


class UserSession:
    """Represents a user's conversation session."""
    
    def __init__(self, line_user_id: str):
        self.line_user_id = line_user_id
        self.pending_action: Optional[str] = None  # e.g., "create_reminder", "add_task"
        self.current_intent: Optional[str] = None
        self.pending_fields: Dict[str, str] = {}
        self.collected_fields: Dict[str, Any] = {}
        self.last_message: str = ""
        self.last_update: datetime = datetime.now()
        self.context_history: list = []
        self.pending_retry_count: int = 0  # Track clarification retries
    
    def update(self, pending_action: str = None, intent: str = None, needs_clarification: bool = False, collected_fields: Dict = None):
        """Update session with new action/intent information."""
        if pending_action:
            self.pending_action = pending_action
            self.pending_retry_count = 0  # Reset retry on new pending
        self.current_intent = intent
        self.collected_fields = collected_fields or {}
        self.last_update = datetime.now()
        
        if needs_clarification:
            pass
    
    def increment_retry(self):
        """Increment retry counter for pending flow."""
        self.pending_retry_count += 1
        return self.pending_retry_count
    
    def reset_retry(self):
        """Reset retry counter."""
        self.pending_retry_count = 0
    
    def add_context(self, message: str, response: str):
        """Add to conversation history."""
        self.context_history.append({
            "user": message,
            "assistant": response,
            "timestamp": datetime.now().isoformat()
        })
        # Keep only last 5 context items
        if len(self.context_history) > 5:
            self.context_history = self.context_history[-5:]
    
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now() - self.last_update > timedelta(minutes=SESSION_TIMEOUT)
    
    def clear(self):
        """Clear the session."""
        self.pending_action = None
        self.current_intent = None
        self.pending_fields = {}
        self.collected_fields = {}
        self.context_history = []
    
    def to_dict(self) -> Dict:
        """Convert session to dictionary."""
        return {
            "line_user_id": self.line_user_id,
            "pending_action": self.pending_action,
            "current_intent": self.current_intent,
            "pending_fields": self.pending_fields,
            "collected_fields": self.collected_fields,
            "last_message": self.last_message,
            "last_update": self.last_update.isoformat(),
            "context_history": self.context_history
        }


def get_session(line_user_id: str) -> UserSession:
    """Get or create a session for a user."""
    if line_user_id not in _user_sessions:
        _user_sessions[line_user_id] = UserSession(line_user_id)
    
    session = _user_sessions[line_user_id]
    
    # Check if session expired
    if session.is_expired():
        logger.info(f"Session expired for {line_user_id}, creating new one")
        _user_sessions[line_user_id] = UserSession(line_user_id)
        session = _user_sessions[line_user_id]
    
    return session


def update_session(
    line_user_id: str,
    pending_action: str = None,
    intent: str = None,
    needs_clarification: bool = False,
    user_message: str = "",
    collected_fields: Optional[Dict] = None
):
    """Update user session with new action/intent."""
    session = get_session(line_user_id)
    
    # New action - update session
    if pending_action:
        session.pending_action = pending_action
    if intent:
        session.current_intent = intent
    
    session.collected_fields = collected_fields or {}
    session.last_message = user_message
    session.last_update = datetime.now()
    
    logger.info(f"Session updated for {line_user_id}: pending_action={pending_action}, intent={intent}, needs_clarification={needs_clarification}")
    return session


def _is_followup_message(previous_intent: str, current_message: str) -> bool:
    """Check if current message is a follow-up to complete previous intent."""
    if previous_intent == "reminder":
        # Check if message contains time or date
        time_keywords = ["โมง", "นาฬิกา", "วัน", "เดือน", "บ่าย", "เช้า", "เย็น", "กี่"]
        return any(kw in current_message for kw in time_keywords)
    
    if previous_intent == "task":
        # Check if message seems to be a task title
        return len(current_message) > 0 and len(current_message) < 100
    
    if previous_intent == "pantry":
        # Check if message seems to be an item name
        return len(current_message) > 0 and len(current_message) < 50
    
    return False


def _extract_fields_from_followup(
    previous_intent: str, 
    current_message: str,
    existing_fields: Dict
) -> Optional[Dict]:
    """Extract fields from follow-up message."""
    message = current_message.lower().strip()
    extracted = {}
    
    if previous_intent == "reminder":
        # Extract time
        import re
        
        # Pattern for time: X โมง, X:00, etc.
        time_match = re.search(r'(\d{1,2})\s*โมง', message)
        if time_match:
            extracted["time"] = time_match.group(1)
        
        # Pattern for date: พรุ่งนี้, วันนี้, วันจันทร์, etc.
        if "พรุ่งนี้" in message or "วันพรุ่ง" in message:
            extracted["date"] = "tomorrow"
        elif "วันนี้" in message:
            extracted["date"] = "today"
        elif "มะรืนนี้" in message:
            extracted["date"] = "day_after_tomorrow"
        
        # Check for "บ่าย" (afternoon)
        if "บ่าย" in message:
            if "บ่ายสอง" in message or "บ่าย 2" in message:
                extracted["time"] = "14"
            elif "บ่ายสาม" in message or "บ่าย 3" in message:
                extracted["time"] = "15"
        
        # Check for "เช้า"
        if "เช้า" in message:
            if "เช้ามาก" in message:
                extracted["time"] = "7"
            else:
                extracted["time"] = "8"
        
        # If no specific time, use the whole message as reminder content if empty
        if not existing_fields.get("message") and extracted:
            extracted["message"] = current_message
    
    elif previous_intent == "task":
        # Use message as task title
        if not existing_fields.get("title"):
            extracted["title"] = current_message.strip()
    
    elif previous_intent == "pantry":
        # Use message as item name
        if not existing_fields.get("item_name"):
            extracted["item_name"] = current_message.strip()
    
    return extracted if extracted else None


def get_session_context(line_user_id: str) -> Dict:
    """Get current session context for a user."""
    session = get_session(line_user_id)
    return session.to_dict()


def clear_session(line_user_id: str):
    """Clear user session."""
    if line_user_id in _user_sessions:
        _user_sessions[line_user_id].clear()
        logger.info(f"Session cleared for {line_user_id}")


def get_recent_context(line_user_id: str, limit: int = 3) -> list:
    """Get recent conversation context."""
    session = get_session(line_user_id)
    return session.context_history[-limit:] if session.context_history else []


def has_pending_intent(line_user_id: str) -> bool:
    """Check if user has a pending intent that needs follow-up."""
    session = get_session(line_user_id)
    return session.current_intent is not None and len(session.collected_fields) == 0


def add_persistent_memory(user_id: str, topic: str, content: str):
    """Add or update a persistent memory for a user (deduplicated by topic)."""
    try:
        from app.repositories.memory_repository import MemoryRepository
        memory_repo = MemoryRepository()
        memory_repo.upsert_by_topic(user_id, topic, content)
        logger.info(f"Memory saved: user={user_id}, topic={topic}")
    except Exception as e:
        logger.error(f"Error saving memory: {e}")


def get_persistent_memories(user_id: str, limit: int = 5):
    """Get latest persistent memories for a user (deduplicated by topic)."""
    try:
        from app.repositories.memory_repository import MemoryRepository
        memory_repo = MemoryRepository()
        result = memory_repo.get_by_user_id(user_id)
        if not result.data:
            return []
        
        topics_seen = {}
        for mem in result.data:
            topic = mem.get("topic")
            if topic not in topics_seen:
                topics_seen[topic] = mem
        
        return list(topics_seen.values())[:limit]
    except Exception as e:
        logger.error(f"Error getting memories: {e}")
        return []


CANCEL_PHRASES = [
    "ยกเลิก", "ไม่แล้ว", "ช่างมัน", "ไม่ต้อง", "เอาไว้ก่อน",
    "ยกเลิกการตั้งเตือน", "ไม่เอาแล้ว", "เลิก", "ปล่อย", "ลืม"
]

# PART 3: Pending Flow Interruption - NEW response for cancel
CANCEL_RESPONSES = {
    "ยกเลิก": "✅ ยกเลิกรายการเรียบร้อยครับ",
    "ไม่เอาแล้ว": "✅ ยกเลิกรายการเรียบร้อยครับ",
    "ช่างมัน": "✅ ยกเลิกรายการเรียบร้อยครับ",
    "ไม่แล้ว": "✅ ยกเลิกรายการเรียบร้อยครับ",
    "ไม่ต้อง": "✅ ยกเลิกรายการเรียบร้อยครับ",
    "เอาไว้ก่อน": "✅ ยกเลิกรายการเรียบร้อยครับ",
    "ยกเลิกการตั้งเตือน": "✅ ยกเลิกการตั้งเตือนเรียบร้อยครับ",
    "เลิก": "✅ ยกเลิกรายการเรียบร้อยครับ",
    "ปล่อย": "✅ ยกเลิกรายการเรียบร้อยครับ",
    "ลืม": "✅ ยกเลิกรายการเรียบร้อยครับ"
}

FRUSTRATION_KEYWORDS = [
    "มึง", "กู", "ห่า", "แม่ม", "เหี้ย", "โง่", "ปัญญาอ่อน",
    "พ่อง", "เหมือนสั่งน้ำมูก", "สั่งเหมือน", "ไร้สาระ",
    "ไม่เก่ง", "ไม่ได้เรื่อง", "ไม่มีประโยชน์", "ไม่ฉลาด"
]

TOPIC_CHANGE_INDICATORS = [
    "แล้วก็", "อีกเรื่อง", "เรื่องอื่น", "เปลี่ยนเรื่อง",
    "ขอถาม", "ถามหน่อย", "มีเรื่อง", "อยากรู้"
]


def classify_reminder_followup(user_message: str) -> str:
    """
    Classify a follow-up message in pending reminder flow.
    
    Returns:
        - "valid_time_reply": Contains valid time for reminder
        - "explicit_cancel": User wants to cancel
        - "topic_change": User changed topic or unrelated
        - "frustration": User is frustrated/angry
        - "invalid_time_reply": Time parsing failed but message is Thai
    """
    msg_lower = user_message.lower().strip()
    
    if any(phrase in msg_lower for phrase in CANCEL_PHRASES):
        logger.info(f"[ReminderFollowup] Classification: explicit_cancel")
        return "explicit_cancel"
    
    if any(kw in msg_lower for kw in FRUSTRATION_KEYWORDS):
        logger.info(f"[ReminderFollowup] Classification: frustration")
        return "frustration"
    
    if any(indicator in msg_lower for indicator in TOPIC_CHANGE_INDICATORS):
        logger.info(f"[ReminderFollowup] Classification: topic_change")
        return "topic_change"
    
    from app.services.reminder_service import reminder_service
    parsed = reminder_service.parse_reminder_message(user_message)
    
    if parsed.get("has_time") and parsed.get("time"):
        logger.info(f"[ReminderFollowup] Classification: valid_time_reply")
        return "valid_time_reply"
    
    if any(kw in msg_lower for kw in ["โมง", "บ่าย", "เช้า", "เย็น", "ทุ่ม", "ตี", "น.", ":", "เวลา"]):
        logger.info(f"[ReminderFollowup] Classification: invalid_time_reply (time-like but not parsed)")
        return "invalid_time_reply"
    
    logger.info(f"[ReminderFollowup] Classification: topic_change (no time detected)")
    return "topic_change"
