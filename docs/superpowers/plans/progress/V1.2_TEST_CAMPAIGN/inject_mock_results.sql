-- ============================================================
-- Mock geo_results injector for Test Campaign 2026-04-20
-- ============================================================
-- Purpose:
--   Bypass the Cloro async scraping pipeline and seed realistic
--   AI-search answer text for Dreame + 杭州天铭科技 so the
--   Analyzer downstream (Brand / Product / Citation parsers)
--   has material to chew on, and the dashboards render charts.
--
-- Why direct-SQL:
--   geo_results has no UI entry point — it's meant to be populated
--   by Cloro's webhook. For integration testing, a mock fixture
--   is the right tool (see feedback_ui_driven_testing.md exception).
--
-- Strategy:
--   For each client, create one client_prompt + one geo_task + N
--   geo_results whose 'text' contains references to the client's
--   own brand, a couple of peers, and tracked product names so
--   the parsers produce Brand/Product/Citation mention rows.
-- ============================================================

-- Turn off some noise during inserts
SET client_min_messages = WARNING;

-- ---------------------------------------------------------------
-- Helper: pick existing IDs we need
-- ---------------------------------------------------------------
WITH
  c_dreame AS (
    SELECT id AS client_id FROM geo_clients WHERE name='Dreame'
  ),
  c_tmax AS (
    SELECT id AS client_id FROM geo_clients WHERE name='杭州天铭科技'
  ),
  t_dreame_robovac AS (
    SELECT id FROM geo_client_topics WHERE client_id=(SELECT client_id FROM c_dreame)
    AND topic_name='Robot Vacuums & Mops' LIMIT 1
  ),
  t_tmax_suspension AS (
    SELECT id FROM geo_client_topics WHERE client_id=(SELECT client_id FROM c_tmax)
    AND topic_name='Suspension & Lift Kits' LIMIT 1
  )
SELECT 'probe' AS step,
  (SELECT client_id FROM c_dreame) AS dreame_id,
  (SELECT client_id FROM c_tmax) AS tmax_id,
  (SELECT id FROM t_dreame_robovac) AS dreame_topic,
  (SELECT id FROM t_tmax_suspension) AS tmax_topic;

-- ---------------------------------------------------------------
-- Dreame: 1 prompt, 1 task, 6 results across ChatGPT/Gemini
-- ---------------------------------------------------------------
DO $$
DECLARE
  v_client uuid;
  v_topic uuid;
  v_prompt uuid;
  v_task uuid;
  v_batch text := 'mock-batch-' || to_char(NOW(), 'YYYYMMDD-HH24MISS');
  v_i int;
  v_platform text;
  v_country text;
  v_lang text;
  v_intent text;
  v_answer text;
BEGIN
  SELECT id INTO v_client FROM geo_clients WHERE name='Dreame';
  SELECT id INTO v_topic FROM geo_client_topics
    WHERE client_id=v_client AND topic_name='Robot Vacuums & Mops' LIMIT 1;

  -- 1 client_prompt
  INSERT INTO geo_client_prompts (id, client_id, topic_id, text, intent, product,
    platform, country, language, is_active)
  VALUES (gen_random_uuid(), v_client, v_topic,
          'best robot vacuum for pet hair and deep carpet in 2026',
          'Solution Discovery', 'Robot Vacuums',
          'chatgpt', 'US', 'en-US', TRUE)
  RETURNING id INTO v_prompt;

  -- 1 task
  INSERT INTO geo_tasks (task_id, client_prompt_id, client_id, topic_id, final_prompt,
    calls_per_prompt, dispatched_count, completed_count, status, batch_id,
    client_name, topic, topic_name, product, platform, country, language, intent,
    client_prompt_text, peers)
  VALUES (gen_random_uuid(), v_prompt, v_client, v_topic,
          'best robot vacuum for pet hair and deep carpet in 2026',
          6, 6, 6, 'COMPLETED', v_batch, 'Dreame', 'Robot Vacuums & Mops',
          'Robot Vacuums & Mops', 'Robot Vacuums', 'chatgpt', 'US', 'en-US',
          'Solution Discovery',
          'best robot vacuum for pet hair and deep carpet in 2026',
          ARRAY['Roborock','iRobot','Ecovacs'])
  RETURNING task_id INTO v_task;

  -- 6 geo_results with varied content
  FOR v_i IN 1..6 LOOP
    -- Alternate platform + intent + intensity of mentions
    IF v_i <= 2 THEN v_platform := 'chatgpt'; v_country := 'US'; v_lang := 'en-US';
    ELSIF v_i <= 4 THEN v_platform := 'gemini'; v_country := 'GB'; v_lang := 'en-GB';
    ELSE v_platform := 'chatgpt'; v_country := 'DE'; v_lang := 'de-DE';
    END IF;

    v_intent := 'Solution Discovery';

    v_answer := CASE v_i
      WHEN 1 THEN
        'For homes with heavy pet shedding, the Dreame X Series Robot Vacuums stand out in 2026. ' ||
        'The flagship Dreame X40 Ultra and its newer sibling (see dreametech.com/products/x40-ultra) ' ||
        'deliver strong suction and automated mop-washing. Close alternatives include the Roborock S8 MaxV Ultra ' ||
        '(roborock.com) and the iRobot Roomba Combo j9+. Our tests found the Dreame L20 Ultra and Dreame L40 Ultra ' ||
        'pulled embedded dog hair out of mid-pile carpet cleaner than the Ecovacs DEEBOT X2 Omni. ' ||
        'Citations: dreametech.com, roborock.com, irobot.com, ecovacs.com.'
      WHEN 2 THEN
        'Top picks: 1) Dreame X40 Ultra — best overall for pets, 2) Roborock S8 MaxV Ultra — strongest LiDAR, ' ||
        '3) Ecovacs DEEBOT X2 Omni — quietest, 4) iRobot Roomba Combo j9+ — best app. ' ||
        'The Dreame L Series Robot Vacuums and X Series Robot Vacuums are well reviewed on dreametech.com. ' ||
        'More at https://us.dreametech.com/collections/robot-vacuums and https://www.roborock.com.'
      WHEN 3 THEN
        'Dreame (追觅) has emerged as a strong challenger to Roborock in 2026. The Dreame X40 Ultra ' ||
        'and Dreame L20 Ultra are currently ranked #1 and #3 in Wirecutter''s robot vacuum roundup. ' ||
        'Runners-up include Roborock Q Revo MaxV and iRobot Roomba j7+. Shop at dreametech.com/uk.'
      WHEN 4 THEN
        'If budget is flexible, the Dreame X40 Ultra offers the best overall performance. For mid-range, ' ||
        'Roborock Q8 Max+ is a strong value. Avoid the older Ecovacs DEEBOT N8 Pro — newer Ecovacs ' ||
        'DEEBOT X2 Omni is significantly better. See rtings.com review and dreametech.com/uk/x40-ultra.'
      WHEN 5 THEN
        'Die besten Saugroboter 2026 für Tierhaare: Dreame X40 Ultra (Testsieger), Roborock S8 MaxV Ultra, ' ||
        'Ecovacs DEEBOT X2 Omni. Der Dreame X40 Ultra überzeugt mit sehr guter Teppichreinigung. ' ||
        'Siehe dreametech.com/de und roborock.com/de.'
      WHEN 6 THEN
        'Preis-Leistungs-Tipp: Dreame L40 Ultra für rund 999€. Dazu im Vergleich: Roborock Qrevo Pro ' ||
        'und iRobot Roomba Combo j9+. Dreame und Roborock dominieren derzeit den Markt. ' ||
        'Quellen: chip.de, dreametech.com/de, roborock.com.'
    END;

    INSERT INTO geo_results (task_id, client_prompt_id, cloro_task_id, call_index,
      cloro_response, http_status_code, latency_ms, text, markdown,
      sources, shopping_cards, places, entities, search_queries, citation_pills,
      client_id, client_name, topic_id, topic, topic_name, product,
      platform, country, language, intent, client_prompt, final_prompt,
      batch_id, peers, owned_domains, ingested_at)
    VALUES (v_task, v_prompt, 'mock-cloro-' || v_task || '-' || v_i, v_i,
      '{"mock": true}'::jsonb, 200, 1500 + (v_i * 100),
      v_answer, v_answer,
      -- sources JSON
      CASE v_i
        WHEN 1 THEN '[{"url":"https://dreametech.com/products/x40-ultra","title":"Dreame X40 Ultra"},{"url":"https://roborock.com","title":"Roborock"},{"url":"https://irobot.com","title":"iRobot"},{"url":"https://ecovacs.com","title":"Ecovacs"}]'::jsonb
        WHEN 2 THEN '[{"url":"https://us.dreametech.com/collections/robot-vacuums","title":"Dreame Robot Vacuums"},{"url":"https://www.roborock.com","title":"Roborock"}]'::jsonb
        WHEN 3 THEN '[{"url":"https://dreametech.com/uk","title":"Dreame UK"},{"url":"https://www.wirecutter.com/reviews/best-robot-vacuum","title":"Wirecutter"}]'::jsonb
        WHEN 4 THEN '[{"url":"https://www.rtings.com","title":"RTINGS"},{"url":"https://dreametech.com/uk/x40-ultra","title":"Dreame X40 Ultra UK"}]'::jsonb
        WHEN 5 THEN '[{"url":"https://dreametech.com/de","title":"Dreame DE"},{"url":"https://roborock.com/de","title":"Roborock DE"}]'::jsonb
        WHEN 6 THEN '[{"url":"https://www.chip.de","title":"CHIP"},{"url":"https://dreametech.com/de","title":"Dreame DE"},{"url":"https://roborock.com","title":"Roborock"}]'::jsonb
      END,
      '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
      v_client, 'Dreame', v_topic, 'Robot Vacuums & Mops', 'Robot Vacuums & Mops',
      'Robot Vacuums', v_platform, v_country, v_lang, v_intent,
      'best robot vacuum for pet hair and deep carpet in 2026',
      'best robot vacuum for pet hair and deep carpet in 2026',
      v_batch,
      ARRAY['Roborock','iRobot','Ecovacs'],
      ARRAY['dreametech.com']::text[],
      NOW() - (v_i || ' hours')::interval);
  END LOOP;
END $$;

-- ---------------------------------------------------------------
-- Tmax: 1 prompt, 1 task, 6 results (Jeep/Truck suspension & lift)
-- Uses Rough Country shadow brand + real peer brands
-- ---------------------------------------------------------------
DO $$
DECLARE
  v_client uuid;
  v_topic uuid;
  v_prompt uuid;
  v_task uuid;
  v_batch text := 'mock-batch-tmax-' || to_char(NOW(), 'YYYYMMDD-HH24MISS');
  v_i int;
  v_platform text;
  v_country text;
  v_lang text;
  v_answer text;
BEGIN
  SELECT id INTO v_client FROM geo_clients WHERE name='杭州天铭科技';
  SELECT id INTO v_topic FROM geo_client_topics
    WHERE client_id=v_client AND topic_name='Suspension & Lift Kits' LIMIT 1;

  INSERT INTO geo_client_prompts (id, client_id, topic_id, text, intent, product,
    platform, country, language, is_active)
  VALUES (gen_random_uuid(), v_client, v_topic,
          'best 3-inch lift kit for Jeep Wrangler JL 2026',
          'Solution Discovery', 'Suspension Lift Kits',
          'chatgpt', 'US', 'en-US', TRUE)
  RETURNING id INTO v_prompt;

  INSERT INTO geo_tasks (task_id, client_prompt_id, client_id, topic_id, final_prompt,
    calls_per_prompt, dispatched_count, completed_count, status, batch_id,
    client_name, topic, topic_name, product, platform, country, language, intent,
    client_prompt_text, peers)
  VALUES (gen_random_uuid(), v_prompt, v_client, v_topic,
          'best 3-inch lift kit for Jeep Wrangler JL 2026',
          6, 6, 6, 'COMPLETED', v_batch, '杭州天铭科技',
          'Suspension & Lift Kits', 'Suspension & Lift Kits',
          'Suspension Lift Kits', 'chatgpt', 'US', 'en-US',
          'Solution Discovery',
          'best 3-inch lift kit for Jeep Wrangler JL 2026',
          ARRAY['Warn Industries','ARB','Superwinch','Smittybilt','Ironman 4x4'])
  RETURNING task_id INTO v_task;

  FOR v_i IN 1..6 LOOP
    IF v_i <= 3 THEN v_platform := 'chatgpt'; v_country := 'US'; v_lang := 'en-US';
    ELSE v_platform := 'gemini'; v_country := 'US'; v_lang := 'en-US';
    END IF;

    v_answer := CASE v_i
      WHEN 1 THEN
        'For a 2026 Jeep Wrangler JL 3-inch lift, top picks are: Rough Country 3.5" Series II, ' ||
        'which retails around $599 and includes shocks. The Rough Country Suspension Lift Kits line ' ||
        'offers good value compared to ARB Old Man Emu and Superwinch suspension kits. ' ||
        'Details at roughcountry.com/jl-wrangler-suspension. Smittybilt also has a budget option.'
      WHEN 2 THEN
        'Rough Country 3.5" Lift with N3 shocks is a popular choice (roughcountry.com). ' ||
        'For higher-end builds, consider ARB or Warn Industries. The Ironman 4x4 Foam Cell kit is ' ||
        'also well-regarded for overlanding. See www.roughcountry.com/products/jl-suspension.'
      WHEN 3 THEN
        'The Rough Country Suspension Lift Kits (3" and 3.5" for Wrangler JL) are the best-selling ' ||
        'budget lifts on Amazon and 4WheelParts. Premium alternatives: ARB, Warn Industries, TJM. ' ||
        'Links: roughcountry.com, arbusa.com.'
      WHEN 4 THEN
        'Best 3-inch Jeep Wrangler JL lift kits in 2026 ranked: 1) Rough Country 3.5" Series II, ' ||
        '2) ARB Old Man Emu BP-51, 3) Superwinch Pro-Series 3in kit. ' ||
        'Rough Country includes N3 shocks standard. See roughcountry.com/jl.'
      WHEN 5 THEN
        'If you want the best price-to-performance, Rough Country 3.5" kit at ~$599 is hard to beat. ' ||
        'Next tier: Ironman 4x4 Foam Cell Pro, TJM XGS. High-end: ARB BP-51 and Warn shock systems. ' ||
        'Review: roughcountry.com.'
      WHEN 6 THEN
        'Budget: Rough Country. Mid: Smittybilt. Premium: ARB, Warn Industries, Ironman 4x4, TJM. ' ||
        'The Rough Country Leveling Lift Kits and Shocks & Struts lines cover most JL build needs. ' ||
        'Full guide at roughcountry.com/jl-wrangler-suspension-lift-kits.'
    END;

    INSERT INTO geo_results (task_id, client_prompt_id, cloro_task_id, call_index,
      cloro_response, http_status_code, latency_ms, text, markdown,
      sources, shopping_cards, places, entities, search_queries, citation_pills,
      client_id, client_name, topic_id, topic, topic_name, product,
      platform, country, language, intent, client_prompt, final_prompt,
      batch_id, peers, owned_domains, ingested_at)
    VALUES (v_task, v_prompt, 'mock-cloro-' || v_task || '-' || v_i, v_i,
      '{"mock": true}'::jsonb, 200, 1500 + (v_i * 100),
      v_answer, v_answer,
      CASE v_i
        WHEN 1 THEN '[{"url":"https://roughcountry.com/jl-wrangler-suspension","title":"Rough Country JL"}]'::jsonb
        WHEN 2 THEN '[{"url":"https://www.roughcountry.com/products/jl-suspension","title":"Rough Country"},{"url":"https://arbusa.com","title":"ARB"}]'::jsonb
        WHEN 3 THEN '[{"url":"https://roughcountry.com","title":"Rough Country"},{"url":"https://arbusa.com","title":"ARB"}]'::jsonb
        WHEN 4 THEN '[{"url":"https://roughcountry.com/jl","title":"Rough Country JL"},{"url":"https://arbusa.com","title":"ARB"},{"url":"https://superwinch.com","title":"Superwinch"}]'::jsonb
        WHEN 5 THEN '[{"url":"https://roughcountry.com","title":"Rough Country"},{"url":"https://www.ironman4x4.com","title":"Ironman 4x4"}]'::jsonb
        WHEN 6 THEN '[{"url":"https://roughcountry.com/jl-wrangler-suspension-lift-kits","title":"Rough Country"},{"url":"https://www.warn.com","title":"Warn"},{"url":"https://arbusa.com","title":"ARB"}]'::jsonb
      END,
      '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
      v_client, '杭州天铭科技', v_topic, 'Suspension & Lift Kits',
      'Suspension & Lift Kits', 'Suspension Lift Kits',
      v_platform, v_country, v_lang, 'Solution Discovery',
      'best 3-inch lift kit for Jeep Wrangler JL 2026',
      'best 3-inch lift kit for Jeep Wrangler JL 2026',
      v_batch,
      ARRAY['Warn Industries','ARB','Superwinch','Smittybilt','Ironman 4x4'],
      ARRAY['roughcountry.com','tmax.cn']::text[],
      NOW() - (v_i || ' hours')::interval);
  END LOOP;
END $$;

-- ---------------------------------------------------------------
-- Verify
-- ---------------------------------------------------------------
SELECT c.name, COUNT(r.*) AS mock_results
FROM geo_clients c
LEFT JOIN geo_results r ON r.client_id = c.id AND r.cloro_task_id LIKE 'mock-cloro-%'
WHERE c.name IN ('Dreame', '杭州天铭科技')
GROUP BY c.name
ORDER BY c.name;
