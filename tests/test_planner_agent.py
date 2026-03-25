"""
Test cases for planner_agent intent classification.
Run with: pytest tests/test_planner_agent.py -v
"""
import pytest
from app.agents.planner_agent import plan_with_intent


class TestCalendarIntent:
    """Test cases for calendar intent classification."""
    
    def test_calendar_tomorrow_meeting(self):
        """'พรุ่งนี้มีประชุมอะไร' → should be calendar"""
        result = plan_with_intent("พรุ่งนี้มีประชุมอะไร")
        assert result["request_type"] == "calendar"
    
    def test_calendar_today_schedule(self):
        """'วันนี้มีอะไรบ้าง' → should be calendar"""
        result = plan_with_intent("วันนี้มีอะไรบ้าง")
        assert result["request_type"] == "calendar"
    
    def test_calendar_friday_appointment(self):
        """'วันศุกร์นี้มีนัดอะไร' → should be calendar"""
        result = plan_with_intent("วันศุกร์นี้มีนัดอะไร")
        assert result["request_type"] == "calendar"
    
    def test_calendar_meeting_schedule(self):
        """'นัดประชุมพรุ่งนี้' → should be calendar"""
        result = plan_with_intent("นัดประชุมพรุ่งนี้")
        assert result["request_type"] == "calendar"


class TestWorkRequestIntent:
    """Test cases for work_request intent classification."""
    
    def test_work_request_help_do(self):
        """'ช่วยทำเรื่องงานให้หน่อย' → should be work_request"""
        result = plan_with_intent("ช่วยทำเรื่องงานให้หน่อย")
        assert result["request_type"] == "work_request"
    
    def test_work_request_create_for(self):
        """'สร้างสไลด์ให้หน่อย' → should be work_request"""
        result = plan_with_intent("สร้างสไลด์ให้หน่อย")
        assert result["request_type"] == "work_request"
    
    def test_work_request_organize(self):
        """'จัดให้หน่อย' → should be work_request"""
        result = plan_with_intent("จัดให้หน่อย")
        assert result["request_type"] == "work_request"
    
    def test_work_request_buy_for(self):
        """'ซื้อของให้หน่อย' → should be work_request"""
        result = plan_with_intent("ซื้อของให้หน่อย")
        assert result["request_type"] == "work_request"


class TestReminderIntent:
    """Test cases for reminder intent classification."""
    
    def test_reminder_tomorrow(self):
        """'เตือนฉันพรุ่งนี้ 8 โมง' → should be reminder"""
        result = plan_with_intent("เตือนฉันพรุ่งนี้ 8 โมง")
        assert result["request_type"] == "reminder"
    
    def test_reminder_in_days(self):
        """'เตือนอีก 3 วัน' → should be reminder"""
        result = plan_with_intent("เตือนอีก 3 วัน")
        assert result["request_type"] == "reminder"


class TestTaskIntent:
    """Test cases for task intent classification."""
    
    def test_task_today_todo(self):
        """'วันนี้ต้องทำอะไรบ้าง' → should be task"""
        result = plan_with_intent("วันนี้ต้องทำอะไรบ้าง")
        assert result["request_type"] == "task"
    
    def test_task_add_work(self):
        """'เพิ่มงาน' → should be task"""
        result = plan_with_intent("เพิ่มงาน")
        assert result["request_type"] == "task"


class TestPantryIntent:
    """Test cases for pantry intent classification."""
    
    def test_pantry_fridge_contents(self):
        """'ของในตู้เย็นมีอะไร' → should be pantry"""
        result = plan_with_intent("ของในตู้เย็นมีอะไร")
        assert result["request_type"] == "pantry"
    
    def test_pantry_buy_meat(self):
        """'ซื้อหมู' → should be pantry"""
        result = plan_with_intent("ซื้อหมู")
        assert result["request_type"] == "pantry"


class TestSearchIntent:
    """Test cases for search intent classification."""
    
    def test_search_info(self):
        """'หาข้อมูลเรื่อง AI' → should be search"""
        result = plan_with_intent("หาข้อมูลเรื่อง AI")
        assert result["request_type"] == "search"
    
    def test_search_howto(self):
        """'วิธีทำข้าวผัด' → should be search"""
        result = plan_with_intent("วิธีทำข้าวผัด")
        assert result["request_type"] == "search"


class TestGeneralChatIntent:
    """Test cases for general_chat intent classification."""
    
    def test_general_greeting(self):
        """'สวัสดี' → should be general_chat"""
        result = plan_with_intent("สวัสดี")
        assert result["request_type"] == "general_chat"
    
    def test_general_hello(self):
        """'hello' → should be general_chat"""
        result = plan_with_intent("hello")
        assert result["request_type"] == "general_chat"


class TestJSONOutput:
    """Test cases for JSON output validation."""
    
    def test_output_has_required_fields(self):
        """Output should have all required fields"""
        result = plan_with_intent("สวัสดี")
        
        assert "request_type" in result
        assert "needs_clarification" in result
        assert "clarification_question" in result
        assert "can_answer_directly" in result
        assert "confidence" in result
        assert "reason" in result
    
    def test_confidence_range(self):
        """Confidence should be between 0 and 1"""
        result = plan_with_intent("สวัสดี")
        
        assert 0.0 <= result["confidence"] <= 1.0
    
    def test_valid_intent(self):
        """Request type should be a valid intent"""
        result = plan_with_intent("สวัสดี")
        
        valid_intents = ["task", "pantry", "reminder", "calendar", "search", "work_request", "general_chat"]
        assert result["request_type"] in valid_intents


class TestEdgeCases:
    """Edge case tests."""
    
    def test_empty_string(self):
        """Empty string should return general_chat"""
        result = plan_with_intent("")
        assert result["request_type"] == "general_chat"
    
    def test_whitespace_only(self):
        """Whitespace only should return general_chat"""
        result = plan_with_intent("   ")
        assert result["request_type"] == "general_chat"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
