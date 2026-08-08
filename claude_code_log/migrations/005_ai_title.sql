-- Add ai_title column to sessions table
-- Migration: 005
-- Description: Stores the session title Claude Code auto-generates by
--              summarising the conversation (ai-title entries in the JSONL).
--              Kept separate from custom_title (manual renames) and summary
--              (compaction summaries) so the three can be prioritised.

ALTER TABLE sessions ADD COLUMN ai_title TEXT;
