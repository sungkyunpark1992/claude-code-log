-- Add custom_title column to sessions table
-- Migration: 004
-- Description: Stores custom session titles from Ctrl+R renames in Claude Code

ALTER TABLE sessions ADD COLUMN custom_title TEXT;
