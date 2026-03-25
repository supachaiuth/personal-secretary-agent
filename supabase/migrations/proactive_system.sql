-- Phase 7: Proactive Assistant System - Database Schema

-- 1. Smart Memory Table (persistent user memories)
CREATE TABLE IF NOT EXISTS user_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_memories_user_topic 
ON user_memories(user_id, topic);

-- 2. Reminder Sent Logs (prevent duplicate advance reminders)
CREATE TABLE IF NOT EXISTS reminder_sent_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reminder_id UUID NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,
    sent_type VARCHAR(50) NOT NULL, -- '5day', '2day', 'same_day', 'due'
    sent_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reminder_sent_logs_reminder 
ON reminder_sent_logs(reminder_id, sent_type);

-- 3. Summary Logs (track morning/daily summaries)
CREATE TABLE IF NOT EXISTS summary_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    summary_type VARCHAR(50) NOT NULL, -- 'morning', 'daily'
    content_summary TEXT,
    sent_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_summary_logs_user_type 
ON summary_logs(user_id, summary_type, sent_at);

-- 4. User Settings (configurable morning summary time)
ALTER TABLE users ADD COLUMN IF NOT EXISTS morning_summary_time TIME DEFAULT '07:45';
ALTER TABLE users ADD COLUMN IF NOT EXISTS morning_summary_enabled BOOLEAN DEFAULT true;
ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_summary_enabled BOOLEAN DEFAULT true;
ALTER TABLE users ADD COLUMN IF NOT EXISTS advance_reminder_enabled BOOLEAN DEFAULT true;

-- 5. Activity Log (track what happened today for daily summary)
CREATE TABLE IF NOT EXISTS activity_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL, -- 'task_created', 'reminder_created', 'pantry_updated', etc.
    activity_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_activity_logs_user_date 
ON activity_logs(user_id, created_at);
