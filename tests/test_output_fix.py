"""
Tests for Output Formatting Defect Fixes

Tests:
1. Remove filler text "รับทราบครับ"
2. Time prefix on task/reminder items
3. Reminder normalization preserving semantic meaning
"""
import pytest
from unittest.mock import patch, MagicMock


class TestOutputFillerRemoval:
    """Part 1: Remove unwanted filler text"""
    
    def test_no_rap_thai_in_summary(self):
        """Daily summary should NOT contain 'รับทราบครับ'"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        
        result = scheduler._format_daily_summary(
            display_name="คุณ",
            tasks_created=1,
            reminders_created=1,
            pantry_updates=0,
            upcoming=[],
            task_items=["คืนคอม lean consult"],
            reminder_items=["08:00 ไปหาหมอ"],
            pantry_items=[]
        )
        
        assert "รับทราบครับ" not in result
        assert "✅" not in result or "รับทราบ" not in result
    
    def test_no_filler_in_agenda(self):
        """Agenda response should NOT start with filler"""
        from app.services.response_handler import normalize_output_v2
        
        result = normalize_output_v2("รับทราบครับ\n• 08:00 ไปหาหมอ", "agenda")
        
        assert not result.startswith("รับทราบ")


class TestTimePrefix:
    """Part 2: Add time prefix to task/reminder items"""
    
    def test_time_prefix_on_task(self):
        """Task with time should display as 'HH:MM - text'"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        
        result = scheduler._format_summary_item(
            text="คืนคอม lean consult",
            time_value="07:00",
            item_type="task"
        )
        
        assert result.startswith("07:00 -")
        assert "คืนคอม" in result
    
    def test_no_time_prefix(self):
        """Task without time should display text only"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        
        result = scheduler._format_summary_item(
            text="คืนคอม lean consult",
            time_value=None,
            item_type="task"
        )
        
        assert result == "คืนคอม lean consult"
        assert "07:00" not in result
    
    def test_iso_time_parsing(self):
        """Should parse ISO datetime format for time prefix"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        
        result = scheduler._format_summary_item(
            text="ไปหาหมอ",
            time_value="2026-03-27T08:00:00Z",
            item_type="reminder"
        )
        
        assert "08:00" in result or "15:00" in result  # Bangkok timezone
        assert "ไปหาหมอ" in result
    
    def test_reminder_with_time_in_summary(self):
        """Reminder in daily summary should have time prefix"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        
        result = scheduler._format_summary_item(
            text="ไปหาหมอ",
            time_value="2026-03-27T08:00:00Z",
            item_type="reminder"
        )
        
        assert "00:00" in result or "15:00" in result  # Bangkok timezone
        assert "ไปหาหมอ" in result


class TestReminderNormalization:
    """Part 3: Fix reminder text normalization"""
    
    def test_preserve_semantic_action(self):
        """Should preserve 'ไปหาหมอ' not output 'เตือน'"""
        from app.services.reminder_service import reminder_service
        
        parsed = {
            "message": "เตือน",
            "time": "08:00",
            "date": "tomorrow",
            "_original": "ช่วยเตือนฉันพรุ่งนี้ 8 โมงไปหาหมอ"
        }
        
        result = reminder_service.normalize_reminder_display(parsed)
        
        assert "เตือน เตือน" not in result
        assert result != "08:00 เตือน"
    
    def test_extract_after_time(self):
        """Should extract action after time expression"""
        from app.services.reminder_service import reminder_service
        
        parsed = {
            "message": "เตือน",
            "time": "08:00",
            "_original": "ช่วยเตือนฉันวันพรุ่งนี้ตอน 8 โมงไปหาหมอ"
        }
        
        result = reminder_service.normalize_reminder_display(parsed)
        
        assert "ไปหาหมอ" in result
        assert "08:00" in result
    
    def test_time_only_if_no_action(self):
        """If no meaningful action, return time only"""
        from app.services.reminder_service import reminder_service
        
        parsed = {
            "message": "",
            "time": "08:00",
            "_original": "เตือน"
        }
        
        result = reminder_service.normalize_reminder_display(parsed)
        
        assert result == "08:00" or "เตือน" not in result
    
    def test_no_duplicate_เตือน(self):
        """Should not output duplicate 'เตือน'"""
        from app.services.response_handler import normalize_output_v2
        
        result = normalize_output_v2("✅ เตือน เตือน ไปหาหมอ", "reminder")
        
        assert "เตือน เตือน" not in result


class TestCompleteSummary:
    """Integration test: Complete daily summary format"""
    
    def test_complete_summary_format(self):
        """Full summary should be properly formatted"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        
        result = scheduler._format_daily_summary(
            display_name="คุณ",
            tasks_created=2,
            reminders_created=2,
            pantry_updates=1,
            upcoming=[],
            task_items=[
                "07:00 - คืนคอม lean consult",
                "09:00 - ประชุม team"
            ],
            reminder_items=[
                "08:00 - ไปหาหมอ",
                "14:00 - กินยา"
            ],
            pantry_items=["เพิ่ม ไข่"]
        )
        
        assert "รับทราบครับ" not in result
        assert "07:00 -" in result
        assert "08:00 -" in result
        assert "• งานใหม่: 2" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])