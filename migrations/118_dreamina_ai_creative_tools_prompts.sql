-- Migration 118: Add Dreamina "AI Creative Tools" topic and prompt set.
--
-- Purpose:
--   Insert the 120 client-supplied keyword-derived prompts as a new Dreamina
--   topic, expanded across the client's existing active platform/country
--   matrix.
--
-- Safety:
--   - Scoped to Dreamina client_id only.
--   - Does not touch existing AI Video / AI Image / AI Design topics.
--   - Aborts if Dreamina is missing, if the expected 60 platform/country/
--     language combinations are not present, if the input set is not exactly
--     120 unique prompts, or if any prompt text already exists in another
--     Dreamina topic.
--   - Inserts 120 * 60 = 7200 rows.
--
-- Rollback:
--   BEGIN;
--   DELETE FROM geo_client_prompts
--    WHERE client_id = 'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid
--      AND topic_id = (
--          SELECT id
--            FROM geo_client_topics
--           WHERE client_id = 'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid
--             AND topic_name = 'AI Creative Tools'
--      );
--   DELETE FROM geo_client_topics
--    WHERE client_id = 'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid
--      AND topic_name = 'AI Creative Tools'
--      AND NOT EXISTS (
--          SELECT 1
--            FROM geo_client_prompts cp
--           WHERE cp.client_id = geo_client_topics.client_id
--             AND cp.topic_id = geo_client_topics.id
--      );
--   COMMIT;

BEGIN;

DO $$
DECLARE
    v_client_id uuid := 'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid;
    v_topic_name text := 'AI Creative Tools';
    v_topic_id uuid;
    v_client_exists integer;
    v_seed_count integer;
    v_seed_unique_count integer;
    v_combo_count integer;
    v_cross_topic_duplicate_count integer;
    v_existing_topic_row_count integer;
    v_insert_count integer := 0;
    v_final_topic_row_count integer;
    v_final_topic_unique_prompt_count integer;
BEGIN
    CREATE TEMP TABLE tmp_dreamina_ai_creative_prompts (
        no integer NOT NULL,
        keyword text NOT NULL,
        prompt_text text NOT NULL
    ) ON COMMIT DROP;

    INSERT INTO tmp_dreamina_ai_creative_prompts (no, keyword, prompt_text)
    VALUES
        (1, 'ai image generator', 'What''s the best AI image generator right now?'),
        (2, 'free ai image generator', 'Is there a free AI image generator that actually works well?'),
        (3, 'best free ai image generator', 'What''s the best free AI image generator with no hidden fees?'),
        (4, 'ai image generator from image', 'Which AI image generator can create new images from an existing image?'),
        (5, 'ai image generator from text', 'What is the best AI image generator from text prompts?'),
        (6, 'ai image generator free online', 'Are there any free AI image generators I can use online without downloading anything?'),
        (7, 'free ai image generator from text', 'Is there a free AI tool that can generate images from text?'),
        (8, 'ai image generator online', 'Which online AI image generator is best to use?'),
        (9, 'best ai image generator free', 'Which free AI image generator gives the best results?'),
        (10, 'realistic ai image generator', 'Which AI image generator creates the most realistic images?'),
        (11, 'ai video generator', 'What''s the best AI video generator in 2026?'),
        (12, 'free ai video generator', 'Is there a free AI video generator?'),
        (13, 'best free ai video generator', 'What''s the best free AI video generator right now?'),
        (14, 'ai video generator free online', 'Are there any free AI video generators available online?'),
        (15, 'ai music video generator', 'Which AI tool is best for generating music videos?'),
        (16, 'ai image to video generator free', 'Is there a free AI tool that can turn images into videos?'),
        (17, 'ai image to video generator', 'What is the best AI image-to-video generator?'),
        (18, 'ai text to video generator free', 'Is there a free AI text-to-video generator?'),
        (19, 'text to video ai generator', 'What is the best AI text-to-video generator right now?'),
        (20, 'ai photo to video generator', 'Which AI tool can turn photos into videos?'),
        (21, 'meme generator', 'What is the best AI meme generator for creating viral memes?'),
        (22, 'AI logo generator', 'Which AI logo generator creates professional logos?'),
        (23, 'logo design', 'What is the best AI tool for logo design?'),
        (24, 'wanted poster maker', 'How can I create a realistic wanted poster using AI?'),
        (25, 'invitation maker', 'Which AI invitation maker is best for creating custom invitations?'),
        (26, 'sticker maker', 'What is the best AI sticker maker?'),
        (27, 'ai headshot generator', 'Which AI photo generator creates realistic headshot?'),
        (28, 'flyer maker', 'What is the best AI flyer maker for marketing materials?'),
        (29, 'business card maker', 'Is there an AI business card maker?'),
        (30, 'business card design', 'How can I design a business card using AI?'),
        (31, 'album cover maker', 'What is the best AI album cover maker?'),
        (32, 'video background remover', 'Which AI tool can remove video backgrounds automatically?'),
        (33, 'ai drawing', 'What is the best AI drawing tool?'),
        (34, 'avatar maker', 'Which AI avatar maker creates realistic avatars?'),
        (35, 'thumbnail maker', 'What is the best AI thumbnail maker?'),
        (36, 'birthday banner', 'How can I create an AI-generated birthday banner?'),
        (37, 'AI design generator', 'What is the best AI design generator?'),
        (38, 't-shirt design', 'Which AI tool is best for creating t-shirt designs?'),
        (39, 'abstract background', 'Can AI generate abstract backgrounds for design projects?'),
        (40, 'book cover design', 'What is the best AI tool for book cover design?'),
        (41, 'profile picture maker', 'Which AI profile picture maker creates professional profile pictures?'),
        (42, 'wallpaper maker', 'What is the best AI wallpaper maker?'),
        (43, 'youtube banner maker', 'Which AI tool can create YouTube banners?'),
        (44, 'ai anime generator', 'What is the best AI anime generator?'),
        (45, 'ai cartoon generator', 'Which AI cartoon generator creates realistic cartoons?'),
        (46, 'youtube thumbnail maker', 'What is the best AI YouTube thumbnail maker?'),
        (47, 'packaging design', 'Which AI tool is best for packaging design?'),
        (48, 'sign maker', 'How can I create custom signs using AI?'),
        (49, 'shirt mockup', 'Which AI mockup generator creates realistic shirt mockups?'),
        (50, 'brochure design', 'What is the best AI tool for brochure design?'),
        (51, 'pokemon trainer card maker', 'How can I create a custom Pokémon trainer card using AI?'),
        (52, 'hoodie design', 'Which AI tool is best for hoodie design?'),
        (53, 'ai portrait generator', 'What is the best AI portrait generator for realistic portraits?'),
        (54, 'ai thumbnail maker', 'Which AI thumbnail maker creates eye-catching thumbnails?'),
        (55, 'album cover art', 'Can AI create professional album cover art?'),
        (56, 'advertisement poster', 'Which AI tool can generate advertisement posters?'),
        (57, 'virtual background', 'What is the best AI virtual background generator?'),
        (58, 'ai album cover generator', 'Which AI album cover generator creates professional designs?'),
        (59, 'ai book cover generator', 'What is the best AI book cover generator?'),
        (60, 'birthday invitation maker', 'Which AI tool creates birthday invitations automatically?'),
        (61, 'digital invitation maker', 'What is the best AI digital invitation maker?'),
        (62, 'wedding invitation design', 'How can I design wedding invitations using AI?'),
        (63, 'AI ad generator', 'What is the best AI ad generator for creating marketing creatives?'),
        (64, 'basketball poster', 'Can AI generate basketball posters automatically?'),
        (65, 'cartoonize photo', 'Which AI tool can turn photos into cartoons?'),
        (66, 'postcard design', 'What is the best AI tool for postcard design?'),
        (67, '3d character creator', 'Which AI tool can create 3D characters?'),
        (68, 'wedding details card', 'Can AI generate elegant wedding details cards?'),
        (69, 'birthday card design', 'What is the best AI tool for birthday card design?'),
        (70, 'brand logo design', 'How can I create a brand logo using AI?'),
        (71, 'label design', 'How can I create product label designs using AI?'),
        (72, 'online card maker', 'Which AI card maker is best for creating custom cards online?'),
        (73, 'birthday poster', 'What is the best AI poster maker for birthdays?'),
        (74, 'ai background changer', 'What is the best AI background changer for photos?'),
        (75, 'ai comic generator', 'What is the best AI comic generator for creating comics?'),
        (76, 'gaming logo maker', 'How can I create gaming logo using AI?'),
        (77, 'ai sharpen image', 'Which AI tool can sharpen blurry images?'),
        (78, 'AI animation video generator', 'What is the best AI animation video generator?'),
        (79, 'AI poster maker', 'What is the best AI poster maker?'),
        (80, 'storyboard maker', 'Which AI tool creates storyboards automatically?'),
        (81, 'ai icon generator', 'What is the best AI icon generator for apps and websites?'),
        (82, 'label creator', 'Which AI label creator is the best?'),
        (83, 'remove blur from image', 'Which AI tool can remove blur from image automatically?'),
        (84, 'custom background', 'Can AI create custom backgrounds for photos?'),
        (85, '3D logo maker', 'Can AI create 3D logos automatically?'),
        (86, 'linkedin banner ideas', 'What are the best AI-generated LinkedIn banner ideas?'),
        (87, 'AI mockup generator', 'What is the best AI mockup generator for product designs?'),
        (88, 'calendar design', 'What is the best AI tool for calendar design?'),
        (89, 'ID card design', 'Can AI generate professional ID card designs?'),
        (90, 'emerald green color palette', 'What are the best emerald green color palettes for design?'),
        (91, 'festival poster', 'Which AI tool creates festival posters?'),
        (92, 'minimalist poster', 'How can I create minimalist posters using AI?'),
        (93, 'scrapbook design', 'Which AI tool is best for creating scrapbook designs?'),
        (94, 'ai landscape generator', 'Which AI landscape generator creates realistic scenery?'),
        (95, 'pixel art ai', 'What is the best AI tool for generating pixel art?'),
        (96, 'AI reel maker', 'Which AI reel maker is best for Instagram and TikTok?'),
        (97, 'mug mockup', 'Which AI mockup generator creates realistic mug mockups?'),
        (98, 'ai artwork generator free', 'Is there a free AI artwork generator?'),
        (99, 'event ticket design', 'How can I design event tickets using AI?'),
        (100, 'magazine cover design', 'Which AI tool creates magazine covers?'),
        (101, 'graduation invitation design', 'How can I create graduation invitations using AI?'),
        (102, 'quote poster', 'What is the best AI tool for quote poster design?'),
        (103, 'trading card design', 'Which AI tool creates custom trading cards?'),
        (104, 'yearbook cover design', 'What is the best AI tool for yearbook cover design?'),
        (105, 'how to make ai art', 'How can I create AI art as a beginner?'),
        (106, 'business flyer design', 'How can I create business flyers using AI?'),
        (107, 'clipart generator', 'What is the best AI clipart generator?'),
        (108, 'baseball card design', 'How can I create baseball cards using AI?'),
        (109, 'holiday photo card', 'How can I create holiday photo cards with AI?'),
        (110, 'play poster', 'Can AI generate theater or play posters?'),
        (111, 'AI banner maker', 'What is the best AI banner maker?'),
        (112, 'online color changer', 'Is there an AI color changer available online?'),
        (113, 'AI wallpaper maker', 'Which AI wallpaper maker is best for creating custom wallpapers?'),
        (114, 'AI video ad maker', 'What is the best AI video ad maker for marketing campaigns?'),
        (115, 'photo book design', 'Which AI tool is best for photo book design?'),
        (116, 'planner design', 'What is the best AI planner design tool?'),
        (117, 'remove background on png', 'How can I remove the background from a PNG image using AI?'),
        (118, 'video invitation maker', 'Which AI tool can create video invitations?'),
        (119, 'ai character art', 'What is the best AI tool for generating character art?'),
        (120, 'ai drawing website', 'What is the best AI drawing website for creating art online?');

    SELECT COUNT(*), COUNT(DISTINCT lower(trim(prompt_text)))
      INTO v_seed_count, v_seed_unique_count
      FROM tmp_dreamina_ai_creative_prompts;

    IF v_seed_count <> 120 OR v_seed_unique_count <> 120 THEN
        RAISE EXCEPTION
            'Abort: expected 120 rows and 120 unique prompt_text values, found rows=%, unique=%',
            v_seed_count, v_seed_unique_count;
    END IF;

    SELECT COUNT(*)
      INTO v_client_exists
      FROM geo_clients
     WHERE id = v_client_id
       AND name = 'Dreamina';

    IF v_client_exists <> 1 THEN
        RAISE EXCEPTION 'Abort: Dreamina client % not found or name mismatch', v_client_id;
    END IF;

    SELECT id
      INTO v_topic_id
      FROM geo_client_topics
     WHERE client_id = v_client_id
       AND topic_name = v_topic_name;

    IF v_topic_id IS NULL THEN
        v_topic_id := gen_random_uuid();

        INSERT INTO geo_client_topics (
            id,
            client_id,
            topic_name,
            topic_type,
            created_at
        )
        VALUES (
            v_topic_id,
            v_client_id,
            v_topic_name,
            'semantic_topic',
            NOW()
        );
    END IF;

    SELECT COUNT(*)
      INTO v_existing_topic_row_count
      FROM geo_client_prompts
     WHERE client_id = v_client_id
       AND topic_id = v_topic_id;

    IF v_existing_topic_row_count NOT IN (0, 7200) THEN
        RAISE EXCEPTION
            'Abort: topic % already has unexpected prompt row count %',
            v_topic_name, v_existing_topic_row_count;
    END IF;

    IF v_existing_topic_row_count = 7200 THEN
        SELECT COUNT(DISTINCT text)
          INTO v_final_topic_unique_prompt_count
          FROM geo_client_prompts
         WHERE client_id = v_client_id
           AND topic_id = v_topic_id;

        IF v_final_topic_unique_prompt_count <> 120 THEN
            RAISE EXCEPTION
                'Abort: existing topic % has 7200 rows but % unique prompts',
                v_topic_name, v_final_topic_unique_prompt_count;
        END IF;

        RAISE NOTICE 'Topic % already appears fully populated; no rows inserted.', v_topic_name;
    ELSE
        SELECT COUNT(*)
          INTO v_combo_count
          FROM (
              SELECT DISTINCT platform, country, language
                FROM geo_client_prompts
               WHERE client_id = v_client_id
                 AND is_active IS TRUE
          ) combos;

        IF v_combo_count <> 60 THEN
            RAISE EXCEPTION
                'Abort: expected 60 active Dreamina platform/country/language combos, found %',
                v_combo_count;
        END IF;

        SELECT COUNT(DISTINCT s.prompt_text)
          INTO v_cross_topic_duplicate_count
          FROM tmp_dreamina_ai_creative_prompts s
          JOIN geo_client_prompts cp
            ON cp.client_id = v_client_id
           AND cp.topic_id <> v_topic_id
           AND lower(trim(cp.text)) = lower(trim(s.prompt_text));

        IF v_cross_topic_duplicate_count <> 0 THEN
            RAISE EXCEPTION
                'Abort: % prompt_text values already exist in other Dreamina topics',
                v_cross_topic_duplicate_count;
        END IF;

        WITH combos AS (
            SELECT DISTINCT platform, country, language
              FROM geo_client_prompts
             WHERE client_id = v_client_id
               AND is_active IS TRUE
        ),
        inserted AS (
            INSERT INTO geo_client_prompts (
                id,
                client_id,
                topic_id,
                text,
                intent,
                product,
                platform,
                country,
                language,
                is_active,
                created_at,
                updated_at
            )
            SELECT
                gen_random_uuid(),
                v_client_id,
                v_topic_id,
                s.prompt_text,
                'Solution Discovery',
                '',
                c.platform,
                c.country,
                c.language,
                TRUE,
                NOW(),
                NOW()
              FROM tmp_dreamina_ai_creative_prompts s
             CROSS JOIN combos c
            RETURNING 1
        )
        SELECT COUNT(*)
          INTO v_insert_count
          FROM inserted;

        IF v_insert_count <> 7200 THEN
            RAISE EXCEPTION
                'Abort: expected to insert 7200 prompt rows, inserted %',
                v_insert_count;
        END IF;
    END IF;

    SELECT COUNT(*), COUNT(DISTINCT text)
      INTO v_final_topic_row_count, v_final_topic_unique_prompt_count
      FROM geo_client_prompts
     WHERE client_id = v_client_id
       AND topic_id = v_topic_id;

    IF v_final_topic_row_count <> 7200 OR v_final_topic_unique_prompt_count <> 120 THEN
        RAISE EXCEPTION
            'Abort: final topic validation failed for %, rows=%, unique_prompts=%',
            v_topic_name, v_final_topic_row_count, v_final_topic_unique_prompt_count;
    END IF;

    RAISE NOTICE
        'Success: Dreamina topic % (%), rows=%, unique_prompts=%',
        v_topic_name, v_topic_id, v_final_topic_row_count, v_final_topic_unique_prompt_count;
END $$;

COMMIT;
