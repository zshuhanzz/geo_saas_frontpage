-- Migration: Add aliases column to geo_clients table
-- This allows clients to have multiple brand name aliases for mention detection

ALTER TABLE geo_clients ADD COLUMN IF NOT EXISTS aliases TEXT[] DEFAULT '{}';
