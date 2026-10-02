-- Migration 015: Add content_generation_model_list to global settings
-- This provides the model picker for Content Generation workflow (mirrors report_model_id_list for Analysis)

INSERT INTO geo_global_settings (key, value, description)
VALUES (
    'content_generation_model_list',
    'gemini-3.1-pro-preview,gemini-3-flash-preview',
    'Comma-separated list of Gemini model IDs available for Content Generation tasks'
)
ON CONFLICT (key) DO NOTHING;
