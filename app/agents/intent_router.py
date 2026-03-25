from dataclasses import dataclass
from typing import Optional


@dataclass
class IntentResult:
    intent: str
    confidence: str
    normalized_text: str


INTENT_KEYWORDS = {
    "task": ["งาน", "ทำ", "task", "todo", "ลิสต์", "รายการ", "ซื้อของ", "จด"],
    "pantry": ["ซื้อ", "ตู้เย็น", "ของในบ้าน", "หมดอายุ", "อาหาร", "วัตถุดิบ", "ของกิน"],
    "reminder": ["เตือน", "reminder", "อีก", "วัน", "นาที", "ชั่วโมง"],
    "calendar": ["นัด", "วันที่", "กำหนด", "ปฏิทิน", "calendar", "คู่"],
    "search": ["หา", "ค้น", "search", "google", "วิธี", "วิธีการ"],
    "work_request": ["สร้าง", "เขียน", "หา", "ค้น", "สรุป", "ร่าง", "brainstorm", "slide", "presentation", "document", "email"],
}


def normalize_text(text: str) -> str:
    return text.strip().lower()


def classify_intent(text: str) -> IntentResult:
    normalized = normalize_text(text)
    scores = {}

    for intent, keywords in INTENT_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword.lower() in normalized:
                score += 1
        if score > 0:
            scores[intent] = score

    if scores:
        top_intent = max(scores.items(), key=lambda x: x[1])[0]
        return IntentResult(
            intent=top_intent,
            confidence="rule",
            normalized_text=text.strip()
        )

    return IntentResult(
        intent="general_chat",
        confidence="rule",
        normalized_text=text.strip()
    )