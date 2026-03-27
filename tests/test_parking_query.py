"""
Tests for Parking Query Intent Detection

Tests:
1. Positive cases - should match
2. Negative cases - should NOT match
3. Normalization
4. Integration with command detector
"""
import pytest
from app.agents.command_detector import is_parking_query, CAR_KEYWORDS, LOCATION_KEYWORDS, _normalize_parking_query


class TestParkingQueryPositive:
    """Positive test cases - should match parking query"""
    
    def test_basic_parking_query(self):
        """ผมจอดรถไว้ที่ไหน → should match"""
        assert is_parking_query("ผมจอดรถไว้ที่ไหน") == True
    
    def test_with_particle_na(self):
        """ผมจอดรถไว้ที่ไหนนะ → should match"""
        assert is_parking_query("ผมจอดรถไว้ที่ไหนนะ") == True
    
    def test_with_question_mark(self):
        """ผมจอดรถไว้ที่ไหน? → should match"""
        assert is_parking_query("ผมจอดรถไว้ที่ไหน?") == True
    
    def test_vehicle_keyword_only(self):
        """รถฉันอยู่ไหน → should match (uses รถ + อยู่ไหน)"""
        assert is_parking_query("รถฉันอยู่ไหน") == True
    
    def test_location_only(self):
        """รถอยู่ตรงไหน → should match"""
        assert is_parking_query("รถอยู่ตรงไหน") == True
    
    def test_floor_query(self):
        """รถอยู่ชั้นไหน → should match"""
        assert is_parking_query("รถอยู่ชั้นไหน") == True
    
    def test_zone_query(self):
        """รถอยู่โซนไหน → should match"""
        assert is_parking_query("รถอยู่โซนไหน") == True
    
    def test_jak_ngai_format(self):
        """รถจอดที่ไหน → should match"""
        assert is_parking_query("รถจอดที่ไหน") == True
    
    def test_teung_where(self):
        """รถอยู่แถวไหน → should match"""
        assert is_parking_query("รถอยู่แถวไหน") == True
    
    def test_vehicle_with_yoo_where(self):
        """รถอยู่ไหน (with อยู่) → should match"""
        assert is_parking_query("รถอยู่ไหน") == True
    
    def test_vehicle_with_na_particle(self):
        """รถอยู่ไหนนะ → should match"""
        assert is_parking_query("รถอยู่ไหนนะ") == True
    
    def test_floor_ari(self):
        """รถอยู่ชั้นอะไร → should match"""
        assert is_parking_query("รถอยู่ชั้นอะไร") == True
    
    def test_vehicle_fang_where(self):
        """รถอยู่ฝั่งไหน → should match"""
        assert is_parking_query("รถอยู่ฝั่งไหน") == True


class TestParkingQueryNegative:
    """Negative test cases - should NOT match parking query"""
    
    def test_restaurant_query(self):
        """ร้านอาหารอยู่ที่ไหน → should NOT match (no รถ)"""
        assert is_parking_query("ร้านอาหารอยู่ที่ไหน") == False
    
    def test_toilet_query(self):
        """ห้องน้ำอยู่ตรงไหน → should NOT match (no รถ)"""
        assert is_parking_query("ห้องน้ำอยู่ตรงไหน") == False
    
    def test_house_query(self):
        """บ้านอยู่ไหน → should NOT match (no รถ)"""
        assert is_parking_query("บ้านอยู่ไหน") == False
    
    def test_only_car_no_location(self):
        """รถ → should NOT match (no location keyword)"""
        assert is_parking_query("รถ") == False
    
    def test_only_location_no_car(self):
        """ที่ไหน → should NOT match (no car keyword)"""
        assert is_parking_query("ที่ไหน") == False
    
    def test_garbage_text(self):
        """abc → should NOT match"""
        assert is_parking_query("abc") == False
    
    def test_too_short(self):
        """ร → should NOT match (too short)"""
        assert is_parking_query("ร") == False
    
    # NEW: False positive cases - should NOT match
    def test_an_which(self):
        """รถอันไหนดีกว่า → should NOT match"""
        assert is_parking_query("รถอันไหนดีกว่า") == False
    
    def test_ban_which(self):
        """รถแบบไหนเหมาะ → should NOT match"""
        assert is_parking_query("รถแบบไหนเหมาะ") == False
    
    def test_kan_which(self):
        """เอารถคันไหนดี → should NOT match"""
        assert is_parking_query("เอารถคันไหนดี") == False
    
    def test_which_is_cheaper(self):
        """อันไหนถูกกว่า → should NOT match"""
        assert is_parking_query("อันไหนถูกกว่า") == False
    
    def test_which_is_better(self):
        """รถอะไรดีกว่า → should NOT match (uses อะไร not อะไร)"""
        assert is_parking_query("รถอะไรดีกว่า") == False
    
    def test_solo_which_without_vehicle(self):
        """ไหน → should NOT match (standalone)"""
        assert is_parking_query("ไหน") == False


class TestNormalization:
    """Test input normalization"""
    
    def test_lowercase(self):
        """Should convert to lowercase"""
        result = _normalize_parking_query("รถอยู่ไหน")
        assert result == "รถอยู่ไหน"
    
    def test_remove_question_mark(self):
        """Should remove ?"""
        result = _normalize_parking_query("รถอยู่ไหน?")
        assert "?" not in result
    
    def test_remove_particle_na(self):
        """Should remove นะ"""
        result = _normalize_parking_query("รถอยู่ไหนนะ")
        assert "นะ" not in result
    
    def test_remove_particle_la(self):
        """Should remove ล่ะ"""
        result = _normalize_parking_query("รถอยู่ไหนล่ะ")
        assert "ล่ะ" not in result
    
    def test_full_normalization(self):
        """Full normalization test"""
        result = _normalize_parking_query("ผมจอดรถไว้ที่ไหนนะ?")
        assert "?" not in result
        assert "นะ" not in result


class TestParkingQueryIntegration:
    """Integration test with command detector"""
    
    def test_parking_query_in_detect_command(self):
        """Parking query should be detected in detect_command"""
        from app.agents.command_detector import detect_command
        
        result = detect_command("รถฉันอยู่ไหน")
        
        assert result is not None
        assert result["action"] == "parking_query"
    
    def test_parking_query_with_time_indicator(self):
        """Parking query should NOT be confused with reminder"""
        from app.agents.command_detector import detect_command
        
        result = detect_command("รถอยู่ไหน 8 โมง")
        
        assert result is not None
        assert result["action"] == "parking_query"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])