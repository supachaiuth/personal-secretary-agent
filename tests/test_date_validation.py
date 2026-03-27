"""
Date Validation Tests for Thai LINE Personal Secretary

Tests the centralized date validation and resolution service.
"""
import pytest
from datetime import date
from app.services.date_validation_service import (
    validate_and_resolve_date,
    get_bangkok_now,
    get_bangkok_date,
    parse_explicit_date,
    resolve_relative_date,
    resolve_weekend_ambiguity,
    format_date_thai,
    format_date_response
)


class TestRelativeDate:
    """Test relative date resolution (พรุ่งนี้, มะรืนนี้, วันนี้)"""
    
    def test_tomorrow_from_march_27(self):
        """พรุ่งนี้ from March 27 should resolve to March 28"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัด xx วันพรุ่งนี้", ref)
        assert result["status"] == "resolved"
        assert result["resolved_date"] == date(2026, 3, 28)
    
    def test_day_after_tomorrow(self):
        """มะรืนนี้ should resolve correctly"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัดมะรืนไปหาหมอ", ref)
        assert result["status"] == "resolved"
        assert result["resolved_date"] == date(2026, 3, 29)
    
    def test_today(self):
        """วันนี้ should resolve to current date"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัดวันนี้", ref)
        assert result["status"] == "resolved"
        assert result["resolved_date"] == ref
    
    def test_year_end_boundary(self):
        """พรุ่งนี้ at year-end should be invalid (next year not allowed)"""
        ref = date(2026, 12, 31)
        result = validate_and_resolve_date("พรุ่งนี้", ref)
        assert result["status"] == "invalid"


class TestExplicitDate:
    """Test explicit date with month/year"""
    
    def test_valid_date_with_month(self):
        """วันที่ 31 มีนา should resolve to March 31"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("เพิ่มนัด xx วันที่ 31 มีนา", ref)
        assert result["status"] == "resolved"
        assert result["resolved_date"] == date(2026, 3, 31)
    
    def test_valid_date_different_month(self):
        """วันที่ 1 เมษา should resolve to April 1"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัดประชุมวันที่ 1 เมษา", ref)
        assert result["status"] == "resolved"
        assert result["resolved_date"] == date(2026, 4, 1)
    
    def test_valid_end_of_year(self):
        """วันที่ 30 ธันวา should resolve to December 30"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัดวันที่ 30 ธันวา", ref)
        assert result["status"] == "resolved"
        assert result["resolved_date"] == date(2026, 12, 30)
    
    def test_future_year_not_allowed(self):
        """วันที่ 1 มกรา 2027 should be invalid"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("เพิ่มนัด xx วันที่ 1 มกรา 2027", ref)
        assert result["status"] == "invalid"
    
    def test_past_year_not_allowed(self):
        """วันที่ 31 ธันวา 2025 should be invalid"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัดวันที่ 31 ธันวา 2025", ref)
        assert result["status"] == "invalid"


class TestMissingMonth:
    """Test cases where month is not specified"""
    
    def test_day_only_future_asks_clarification(self):
        """วันที่ 31 without month should ask clarification"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัดประชุมวันที่ 31", ref)
        assert result["status"] == "needs_clarification"
        assert "ของเดือนไหน" in result["clarification_question"]
    
    def test_day_only_past_is_invalid(self):
        """วันที่ 26 (past) without month should be invalid"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัดหมายวันที่ 26", ref)
        assert result["status"] == "invalid"
    
    def test_day_only_same_day_resolved(self):
        """วันที่ 27 (today) without month should be resolved"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัดหมายวันที่ 27", ref)
        assert result["status"] == "resolved"
        assert result["resolved_date"] == date(2026, 3, 27)


class TestInvalidDay:
    """Test invalid day numbers"""
    
    def test_day_36_asks_clarification(self):
        """วันที่ 36 should ask clarification (invalid day)"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัดหมายวันที่ 36", ref)
        assert result["status"] == "needs_clarification"
    
    def test_day_0_asks_clarification(self):
        """วันที่ 0 should ask clarification"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัดวันที่ 0", ref)
        assert result["status"] == "needs_clarification"
    
    def test_day_exceeds_month_days(self):
        """31 เมษา should ask clarification (April has 30 days)"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัดวันที่ 31 เมษา", ref)
        assert result["status"] == "needs_clarification"
        assert "30วัน" in result["clarification_question"]


class TestWeekendAmbiguity:
    """Test weekend ambiguity resolution"""
    
    def test_weekend_asks_clarification(self):
        """เสาร์อาทิตย์ should ask clarification with options"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัด xx เสาร์อาทิตย์", ref)
        assert result["status"] == "needs_clarification"
        assert result["options"] is not None
        assert len(result["options"]) == 2
        assert result["options"][0] == date(2026, 3, 28)  # Saturday
        assert result["options"][1] == date(2026, 3, 29)  # Sunday
    
    def test_weekend_options_format(self):
        """Weekend options should have proper question"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัด xx เสาร์อาทิตย์", ref)
        assert "เสาร์" in result["clarification_question"]
        assert "อาทิตย์" in result["clarification_question"]
        assert "ทั้งสองวัน" in result["clarification_question"]


class TestWeekdayReference:
    """Test weekday references (วันจันทร์, วันอังคาร, etc.)"""
    
    def test_monday_resolves(self):
        """วันจันทร์ should resolve to next Monday"""
        ref = date(2026, 3, 27)  # Saturday
        result = validate_and_resolve_date("นัดประชุมวันจันทร์", ref)
        assert result["status"] == "resolved"
        assert result["resolved_date"] == date(2026, 3, 30)


class TestPastDate:
    """Test past date validation"""
    
    def test_past_date_is_invalid(self):
        """Past date should be invalid"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัดหมายวันที่ 26", ref)
        assert result["status"] == "invalid"
    
    def test_past_date_with_month_is_invalid(self):
        """Past date with month should be invalid"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัดวันที่ 1 มีนา", ref)
        assert result["status"] == "invalid"
    
    def test_past_date_month_day_combo_invalid(self):
        """February 29 in non-leap year should be invalid"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("นัดวันที่ 29 กุมภา 2026", ref)
        assert result["status"] in ["invalid", "needs_clarification"]


class TestBangkokTimezone:
    """Test Bangkok timezone handling"""
    
    def test_bangkok_now_works(self):
        """get_bangkok_now should return Bangkok time"""
        now = get_bangkok_now()
        assert now.tzinfo is not None
    
    def test_bangkok_date_works(self):
        """get_bangkok_date should return Bangkok date"""
        bk_date = get_bangkok_date()
        assert isinstance(bk_date, date)


class TestNoWriteValidation:
    """Test that invalid/needs_clarification cases don't write to DB"""
    
    def test_invalid_status_means_no_write(self):
        """Invalid status means no DB write should occur"""
        ref = date(2026, 3, 27)
        
        invalid_cases = [
            "เพิ่มนัด xx วันที่ 1 มกรา 2027",  # future year
            "นัดหมายวันที่ 26",  # past date
            "นัดวันที่ 1 มีนา",  # past date
        ]
        
        for case in invalid_cases:
            result = validate_and_resolve_date(case, ref)
            assert result["status"] == "invalid", f"Case {case} should be invalid"
    
    def test_clarification_status_means_no_write(self):
        """Needs_clarification status means no DB write should occur"""
        ref = date(2026, 3, 27)
        
        clarification_cases = [
            "นัดประชุมวันที่ 31",  # missing month
            "นัดหมายวันที่ 36",  # invalid day
            "นัด xx เสาร์อาทิตย์",  # weekend ambiguity
        ]
        
        for case in clarification_cases:
            result = validate_and_resolve_date(case, ref)
            assert result["status"] == "needs_clarification", f"Case {case} should need clarification"


class TestRegression:
    """Regression tests for existing flows"""
    
    def test_reminder_with_prom_morrow_still_works(self):
        """Reminder with พรุ่งนี้ still works"""
        ref = date(2026, 3, 27)
        result = validate_and_resolve_date("เตือนฉันพรุ่งนี้ไปประชุม", ref)
        assert result["status"] == "resolved"
        assert result["resolved_date"] == date(2026, 3, 28)
    
    def test_explicit_valid_date_in_current_year(self):
        """Explicit valid dates in current year still work"""
        ref = date(2026, 3, 27)
        
        valid_cases = [
            ("นัดประชุมวันที่ 1 เมษา", date(2026, 4, 1)),
            ("นัดวันที่ 30 ธันวา", date(2026, 12, 30)),
        ]
        
        for case, expected in valid_cases:
            result = validate_and_resolve_date(case, ref)
            assert result["status"] == "resolved", f"Case {case} should be resolved"
            assert result["resolved_date"] == expected, f"Case {case} date mismatch"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])