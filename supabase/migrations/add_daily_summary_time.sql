-- Add configurable daily_summary_time column
ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_summary_time TIME DEFAULT '20:00';
