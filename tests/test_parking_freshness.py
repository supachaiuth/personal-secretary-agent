"""
Tests for Parking Freshness Logic in Daily Summary

Tests:
1. days_diff <= 1 → normal message
2. days_diff == 2 → show days_diff
3. days_diff == 3 → show days_diff
4. days_diff >= 4 → don't show
5. no parking data → don't show
"""
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock


BANGKOK_TZ = ZoneInfo("Asia/Bangkok")


class TestParkingFreshness:
    """Test parking freshness logic"""
    
    def _make_parking_data(self, days_ago: int) -> dict:
        """Create mock parking data with updated_at days_ago from now."""
        updated = datetime.now(BANGKOK_TZ) - timedelta(days=days_ago)
        return {
            "content": "ชั้น 5B",
            "updated_at": updated.isoformat()
        }
    
    def test_parking_today(self):
        """Case 1: updated today → show normal message"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        parking = self._make_parking_data(0)
        
        result = scheduler._format_parking_message(parking)
        
        assert result is not None
        assert "ชั้น 5B" in result
        assert "วันที่แล้ว" not in result
    
    def test_parking_yesterday(self):
        """Case 1: updated yesterday → show normal message"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        parking = self._make_parking_data(1)
        
        result = scheduler._format_parking_message(parking)
        
        assert result is not None
        assert "ชั้น 5B" in result
        assert "วันที่แล้ว" not in result
    
    def test_parking_2_days_ago(self):
        """Case 2: updated 2 days ago → show days_diff"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        parking = self._make_parking_data(2)
        
        result = scheduler._format_parking_message(parking)
        
        assert result is not None
        assert "ชั้น 5B" in result
        assert "2 วันที่แล้ว" in result
    
    def test_parking_3_days_ago(self):
        """Case 3: updated 3 days ago → show days_diff"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        parking = self._make_parking_data(3)
        
        result = scheduler._format_parking_message(parking)
        
        assert result is not None
        assert "ชั้น 5B" in result
        assert "3 วันที่แล้ว" in result
    
    def test_parking_4_days_ago(self):
        """Case 4: updated 4 days ago → don't show"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        parking = self._make_parking_data(4)
        
        result = scheduler._format_parking_message(parking)
        
        assert result is None
    
    def test_parking_5_days_ago(self):
        """Case 4: updated 5 days ago → don't show"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        parking = self._make_parking_data(5)
        
        result = scheduler._format_parking_message(parking)
        
        assert result is None
    
    def test_no_parking_data(self):
        """Case 5: no parking data → don't show"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        
        result = scheduler._format_parking_message(None)
        
        assert result is None
    
    def test_empty_parking_data(self):
        """Case 5: empty parking data → don't show"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        
        result = scheduler._format_parking_message({})
        
        assert result is None
    
    def test_parking_message_format_days_diff(self):
        """Verify format for days_diff == 2"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        parking = self._make_parking_data(2)
        
        result = scheduler._format_parking_message(parking)
        
        assert "จอดรถที่ชั้น 5B (เมื่อ 2 วันที่แล้ว)" == result
    
    def test_parking_message_format_today(self):
        """Verify format for today"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        parking = self._make_parking_data(0)
        
        result = scheduler._format_parking_message(parking)
        
        assert "คุณจอดรถไว้ที่ ชั้น 5B" == result


class TestDailySummaryParkingIntegration:
    """Test parking integration in daily summary"""
    
    def test_daily_summary_with_fresh_parking(self):
        """Daily summary includes fresh parking"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        
        parking = {
            "content": "ชั้น 5B",
            "updated_at": datetime.now(BANGKOK_TZ).isoformat()
        }
        
        result = scheduler._format_daily_summary(
            display_name="คุณ",
            tasks_created=1,
            reminders_created=1,
            pantry_updates=0,
            upcoming=[],
            task_items=["07:00 - คืนคอม"],
            reminder_items=["08:00 - ไปหาหมอ"],
            pantry_items=[],
            today_parking=parking
        )
        
        assert "ชั้น 5B" in result
        assert "วันที่แล้ว" not in result
    
    def test_daily_summary_with_old_parking(self):
        """Daily summary does NOT include old parking (4+ days)"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        
        parking = {
            "content": "ชั้น 5B",
            "updated_at": (datetime.now(BANGKOK_TZ) - timedelta(days=4)).isoformat()
        }
        
        result = scheduler._format_daily_summary(
            display_name="คุณ",
            tasks_created=1,
            reminders_created=1,
            pantry_updates=0,
            upcoming=[],
            task_items=["07:00 - คืนคอม"],
            reminder_items=["08:00 - ไปหาหมอ"],
            pantry_items=[],
            today_parking=parking
        )
        
        assert "ชั้น" not in result
        assert "จอดรถ" not in result
    
    def test_daily_summary_no_parking(self):
        """Daily summary without parking data"""
        from app.services.scheduler_service import ProactiveScheduler
        
        scheduler = ProactiveScheduler()
        
        result = scheduler._format_daily_summary(
            display_name="คุณ",
            tasks_created=1,
            reminders_created=1,
            pantry_updates=0,
            upcoming=[],
            task_items=["07:00 - คืนคอม"],
            reminder_items=["08:00 - ไปหาหมอ"],
            pantry_items=[],
            today_parking=None
        )
        
        assert "จอดรถ" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])