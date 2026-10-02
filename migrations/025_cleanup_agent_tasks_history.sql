-- Migration 025: Clean up historical geo_agent_tasks data
-- Date: 2026-04-06
-- Description: Delete all historical task data (development/testing artifacts)

DELETE FROM geo_agent_tasks;
