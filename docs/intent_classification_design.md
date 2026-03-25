# Intent Classification System

## Current Problem
- Keyword-based detection causes ambiguity:
  - "เพิ่มซื้อหมู" → pantry? task?
  - Hard to distinguish similar phrases

## New Classification Flow

```
User Message
     │
     ▼
┌─────────────────────┐
│ Level 1: Explicit   │ ← Fast regex patterns
│ Patterns            │   (เพิ่มงาน, เตือน, ซื้อ, etc.)
└─────────┬───────────┘
          │ Match
          ▼
     ACTION DETECTED
          │
     No Match
          ▼
┌─────────────────────┐
│ Level 2: AI         │ ← Lightweight classification
│ Classification      │   (gpt-4o-mini, cached)
└─────────┬───────────┘
          │ Classified
          ▼
     ACTION DETECTED
          │
     Failed
          ▼
┌─────────────────────┐
│ Level 3: Keyword    │ ← Last resort
│ Fallback           │
└─────────┬───────────┘
          │
          ▼
     ACTION / FALLBACK
```

## Classification Categories

| Intent | Description | Examples |
|--------|-------------|----------|
| `add_task` | Add a todo/work task | เพิ่มงานประชุม, งานซื้อของ |
| `add_pantry` | Add grocery/food item | ซื้อหมู, เพิ่มผัก |
| `create_reminder` | Set a reminder | เตือนผมพรุ่งนี้, อย่าลืม... |
| `list_tasks` | View tasks | ดูงาน, มีงานอะไร |
| `list_pantry` | View pantry items | ดูตู้เย็น, มีอะไรในครัว |
| `chat` | General conversation | สวัสดี, หิวข้าว |

## AI Classification Prompt

```
Classify this Thai message into one of:
- add_task (งาน, ภารกิจ, todo, ต้องทำ)
- add_pantry (ซื้อ, เพิ่ม, ของกิน, อาหาร, ตู้เย็น, ครัว)
- create_reminder (เตือน, แจ้งเตือน, อย่าลืม)
- list_tasks (ดูงาน, รายการงาน)
- list_pantry (ดูตู้เย็น, มีอะไรบ้าง)
- chat (anything else)

Message: {user_message}

Respond with ONLY the intent word, nothing else.
```

## Performance Optimizations

1. **Caching**: Cache AI results by message hash (1 hour TTL)
2. **Fast Model**: Use gpt-4o-mini (fastest/cheapest)
3. **Timeout**: 5 second timeout for AI calls
4. **Fallback**: If AI fails, use keyword fallback

## Backward Compatibility

- Explicit patterns still work exactly as before
- Keyword fallback still available
- Only AI is added as middle layer
- No breaking changes to existing behavior
