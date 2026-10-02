-- ============================================================
-- Migration 046b: Hotfix brand_sentiment_breakdown metric 的 is_own_brand 引用
-- ============================================================
-- 问题:046 主迁移里的简单 replace() 只覆盖了 WHERE is_own_brand = true/false,
--   没覆盖 `cm.is_own_brand` 作为 SELECT 列 / GROUP BY key / ORDER BY key 的情况
-- 这里做一次针对性替换:
--   cm.is_own_brand → (cm.brand_role = 'own') AS is_own_brand (在 SELECT 里派生,保持列名不变)
--   或直接替换为 cm.brand_role(如果下游消费方已适配)
--
-- 为了最小影响下游消费(前端/Agent 可能预期 is_own_brand 列名),此处用派生列方式
-- ============================================================

BEGIN;

UPDATE geo_analysis_metrics
   SET calculation_hint = replace(
                            replace(
                              replace(
                                replace(
                                  calculation_hint,
                                  'GROUP BY cm.brand_name, cm.is_own_brand',
                                  'GROUP BY cm.brand_name, cm.brand_role'
                                ),
                                'cm.is_own_brand,',
                                '(cm.brand_role = ''own'') AS is_own_brand,'
                              ),
                              'GROUP BY brand_name, is_own_brand',
                              'GROUP BY brand_name, is_own_brand'  -- 已经用派生列 alias,无需改
                            ),
                            'ORDER BY is_own_brand DESC',
                            'ORDER BY is_own_brand DESC'  -- 派生列 alias 可正常排序
                          ),
       description = replace(description,
                             'JOIN geo_brand_mentions 获取 brand_name 和 is_own_brand',
                             'JOIN geo_brand_mentions 获取 brand_name 和 brand_role(派生 is_own_brand)'),
       updated_at = NOW()
 WHERE metric_name = 'brand_sentiment_breakdown';

COMMIT;

-- 验证:残留的 cm.is_own_brand 应为 0
-- SELECT COUNT(*) FROM geo_analysis_metrics WHERE calculation_hint LIKE '%cm.is_own_brand%';
-- 期望:0

-- SELECT calculation_hint FROM geo_analysis_metrics WHERE metric_name='brand_sentiment_breakdown';
-- 检查:SELECT 子句应含 (cm.brand_role = 'own') AS is_own_brand
