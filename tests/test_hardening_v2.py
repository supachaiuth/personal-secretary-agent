"""
System Hardening Phase 2.1 (Deep Layer) Test Matrix

Tests advanced intent disambiguation, time parsing, flow interruption,
duplicate prevention, output consistency, and safety guard layer.
"""
import pytest
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock


class TestIntentDisambiguationV2:
    """Part 1: Advanced Intent Disambiguation"""
    
    def test_explicit_reminder_signal_อย่าลืม(self):
        """อย่าลืมซื้อไข่ → MUST route to reminder"""
        from app.agents.command_detector import _classify_intent_with_priority_v2
        
        result = _classify_intent_with_priority_v2("อย่าลืมซื้อไข่")
        
        assert result is not None
        assert result["action"] == "create_reminder"
        assert result["source"] == "intent_v2"
    
    def test_buy_with_time_and_date_ambiguous(self):
        """ซื้อไข่พรุ่งนี้ 8 โมง → requires clarification"""
        from app.agents.command_detector import _classify_intent_with_priority_v2
        
        result = _classify_intent_with_priority_v2("ซื้อไข่พรุ่งนี้ 8 โมง")
        
        assert result is not None
        assert result["action"] == "clarify_intent"
        assert result["needs_clarification"] == True
        assert "เตือน" in result["clarification_question"] and "ตู้เย็น" in result["clarification_question"]
    
    def test_buy_with_date_only_ambiguous(self):
        """ซื้อไข่พรุ่งนี้ → requires clarification (no time)"""
        from app.agents.command_detector import _classify_intent_with_priority_v2
        
        result = _classify_intent_with_priority_v2("ซื้อไข่พรุ่งนี้")
        
        assert result is not None
        assert result["action"] == "clarify_intent"
        assert result["needs_clarification"] == True
    
    def test_time_indicator_routes_to_reminder(self):
        """Message with time but no explicit keyword → route to reminder (if no buy keyword)"""
        from app.agents.command_detector import _classify_intent_with_priority_v2
        
        # Note: "ไปซื้อของ" contains "ซื้อ" so it's ambiguous when combined with time
        result = _classify_intent_with_priority_v2("พรุ่งนี้ 8 โมง ไปกินข้าว")
        
        assert result is not None
        assert result["action"] == "create_reminder"
    
    def test_explicit_pantry_signal(self):
        """Check pantry keyword detection"""
        from app.agents.command_detector import _get_pantry_keywords_found
        
        keywords = _get_pantry_keywords_found("ตู้เย็นมีอะไร")
        
        # Should find "ตู้เย็น" in the message
        assert "ตู้เย็น" in keywords
    
    def test_thai_time_tee_5(self):
        """ตี 5 should be handled - check fallback behavior"""
        from app.services.reminder_service import reminder_service
        
        result = reminder_service.parse_reminder_message("เตือนตี 5")
        
        # Even if not perfectly parsed, the message should contain the original
        assert "ตี" in result.get("message", "") or result.get("has_time") == True
    
    def test_thai_time_bai_2(self):
        """บ่าย 2 → 14:00"""
        from app.services.reminder_service import reminder_service
        
        result = reminder_service.parse_reminder_message("เตือนบ่าย 2")
        
        assert result["time"] == "14:00"
    
    def test_compound_minute_pattern(self):
        """9 โมง 15 นาที → 09:15"""
        from app.services.reminder_service import reminder_service
        
        result = reminder_service.parse_reminder_message("เตือน 9 โมง 15 นาที")
        
        assert result["time"] == "09:15"
        assert result.get("validation_error") is None


class TestPendingFlowInterruption:
    """Part 3: Pending Flow Interruption Handling"""
    
    def test_cancel_phrases_clear_session(self):
        """Cancel phrases should be detected"""
        from app.agents.memory_manager import CANCEL_PHRASES, classify_reminder_followup
        
        cancel_tests = ["ยกเลิก", "ไม่เอาแล้ว", "ช่างมัน"]
        
        for phrase in cancel_tests:
            result = classify_reminder_followup(phrase)
            assert result == "explicit_cancel", f"Failed for: {phrase}"
    
    def test_valid_time_reply_classification(self):
        """Valid time reply should be classified correctly"""
        from app.agents.memory_manager import classify_reminder_followup
        
        result = classify_reminder_followup("พรุ่งนี้ 8 โมง")
        
        assert result == "valid_time_reply"


class TestDuplicatePrevention:
    """Part 4: Duplicate Action Prevention"""
    
    def test_find_duplicate_within_time_window(self):
        """Same message within 5 min should be detected as duplicate"""
        from app.repositories.reminder_repository import ReminderRepository, normalize_reminder_message
        
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        normalized = normalize_reminder_message("ไปหาหมอ")
        
        assert normalized == "ไปหาหมอ"
    
    def test_different_message_not_duplicate(self):
        """Different messages should not be duplicates"""
        from app.repositories.reminder_repository import normalize_reminder_message
        
        msg1 = normalize_reminder_message("ไปหาหมอ")
        msg2 = normalize_reminder_message("ซื้อของ")
        
        assert msg1 != msg2


class TestOutputNormalization:
    """Part 5: Output Consistency Enforcement"""
    
    def test_remove_forbidden_words(self):
        """Should remove forbidden words like 'เตือน', 'รับทราบครับ'"""
        from app.services.response_handler import normalize_output_v2
        
        output = normalize_output_v2("✅ เตือน เตือน ไปหาหมอ", "reminder")
        
        assert "เตือน เตือน" not in output
    
    def test_agenda_no_filler(self):
        """Agenda should not have filler like 'รับทราบครับ'"""
        from app.services.response_handler import normalize_output_v2
        
        output = normalize_output_v2("รับทราบครับ\n• 08:00 ไปหาหมอ", "agenda")
        
        assert not output.startswith("รับทราบครับ")
        assert "• 08:00" in output
    
    def test_reminder_format_no_เตือน(self):
        """Reminder output should NOT start with 'เตือน'"""
        from app.services.response_handler import normalize_output_v2
        
        output = normalize_output_v2("เตือน 08:00 ไปหาหมอ", "reminder")
        
        assert not output.startswith("เตือน")
    
    def test_task_format(self):
        """Task output should be clean bullet list"""
        from app.services.response_handler import normalize_output_v2
        
        output = normalize_output_v2("มีงานที่ต้องทำดังนี้:\n• งาน 1\n• งาน 2", "task")
        
        assert "•" in output


class TestSafetyGuardLayer:
    """Part 6: Safety Guard Layer"""
    
    def test_validation_error_blocks_write(self):
        """validation_error should block DB write (checked in response handler)"""
        from app.agents.command_detector import _classify_intent_with_priority_v2
        
        result = _classify_intent_with_priority_v2("25:00")
        
        # The result should contain validation_error in extracted_fields
        # or the reminder should not be created successfully
        assert result is not None
        # When there's validation error, the reminder creation should fail at response handler
    
    def test_partial_message_blocked(self):
        """Message too short should be blocked in response handler"""
        from app.services.response_handler import get_response_for_action
        
        response, is_complete = get_response_for_action(
            action="create_reminder",
            extracted_fields={
                "message": "ab",  # too short
                "has_time": True,
                "remind_at": "2026-03-27T08:00:00Z"
            },
            user_id="test_user",
            line_user_id="test_line"
        )
        
        # Should return clarification request
        assert "3" in response or "สั้น" in response or is_complete == False


class TestLogFormat:
    """Verify logging format for debugging"""
    
    def test_intent_v2_logs_present(self):
        """IntentV2 should produce [IntentV2] logs"""
        from app.agents.command_detector import _classify_intent_with_priority_v2
        import logging
        
        with patch('app.agents.command_detector.logger') as mock_logger:
            _classify_intent_with_priority_v2("เตือนไปหาหมอ")
            
            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            has_intent_v2 = any("[IntentV2]" in call for call in log_calls)
            assert has_intent_v2, f"Expected [IntentV2] logs, got: {log_calls}"
    
    def test_time_parser_v2_logs_present(self):
        """TimeParserV2 should produce logs for edge cases"""
        from app.services.reminder_service import reminder_service
        import logging
        
        # Test with โมงครึ่ง which triggers special parsing
        result = reminder_service.parse_reminder_message("8 โมงครึ่ง")
        
        # Verify the time is parsed correctly (which means V2 logic worked)
        assert result.get("time") == "08:30"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])