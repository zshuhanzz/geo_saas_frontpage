"""
GEO Analyzer - Main Entry Point

Cloud Run Job that processes geo_results for a specific report,
extracting company mentions and citations into structured tables.

Usage:
    REPORT_ID=xxx python main.py
"""
import os
import sys
import logging
from sqlalchemy import text
from src.core.database import get_db_connection
from src.parsers.company_parser import parse_company_mentions
from src.parsers.citation_parser import parse_citations

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("GeoAnalyzer")


def main():
    """Main entry point for the analyzer job."""
    report_id = os.environ.get("REPORT_ID")
    
    if not report_id:
        logger.error("REPORT_ID environment variable is required")
        sys.exit(1)
    
    logger.info(f"[ANALYZER-S0] ========== GEO Analyzer 启动 ==========")
    logger.info(f"[ANALYZER-S0] Report ID: {report_id}")
    
    try:
        with get_db_connection() as conn:
            # 1. Get unanalyzed count (optional, for logging)
            logger.info(f"[ANALYZER-S1] 查询未分析的 results 数量...")
            total_unanalyzed = conn.execute(text("""
                SELECT COUNT(*) FROM geo_results 
                WHERE report_id = :report_id AND analyzed_at IS NULL
            """), {"report_id": report_id}).scalar()
            
            logger.info(f"[ANALYZER-S1] 找到 {total_unanalyzed} 条未分析记录")
            
            if total_unanalyzed == 0 and not os.environ.get("FORCE_RUN"):
                logger.info("[ANALYZER-S1] 没有需要分析的数据")
                # Even if no data, check if we should complete the report
                # Fallthrough to completion check
            
            # 3. Batch Process Loop
            BATCH_SIZE = 100
            total_processed = 0
            mentions_count = 0
            citations_count = 0
            
            while True:
                # Get next batch of unanalyzed results
                # Using LIMIT to process in chunks
                logger.info(f"[ANALYZER-S2] Fetching next batch (limit={BATCH_SIZE})...")
                results = conn.execute(text("""
                    SELECT * FROM geo_results 
                    WHERE report_id = :report_id AND analyzed_at IS NULL
                    LIMIT :limit
                """), {"report_id": report_id, "limit": BATCH_SIZE}).fetchall()
                
                if not results:
                    break
                    
                batch_count = len(results)
                logger.info(f"[ANALYZER-S2] Processing batch of {batch_count} results...")
                
                # Process the batch
                for result in results:
                    result_id = result.result_id
                    
                    # Parse company mentions
                    mentions = parse_company_mentions(
                        result.text or "",
                        result.client_name,
                        result.peers or []
                    )
                    
                    # Parse citations
                    citations = parse_citations(
                        result.sources or [],
                        result.citation_pills or [],
                        result.owned_domains or []
                    )
                    
                    # Insert mentions
                    for m in mentions:
                        conn.execute(text("""
                            INSERT INTO geo_company_mentions 
                            (report_id, request_id, task_id, result_id, client_id,
                             company_name, mention_position, is_client, is_peer,
                             client_name, platform, intent, topic, product, country, executed_at)
                            VALUES (:report_id, :request_id, :task_id, :result_id, :client_id,
                                    :company_name, :mention_position, :is_client, :is_peer,
                                    :client_name, :platform, :intent, :topic, :product, :country, :executed_at)
                        """), {
                            "report_id": result.report_id,
                            "request_id": result.request_id,
                            "task_id": result.task_id,
                            "result_id": result.result_id,
                            "client_id": result.client_id,
                            "company_name": m["company_name"],
                            "mention_position": m["mention_position"],
                            "is_client": m["is_client"],
                            "is_peer": m["is_peer"],
                            "client_name": result.client_name,
                            "platform": result.platform,
                            "intent": result.intent,
                            "topic": result.topic,
                            "product": result.product,
                            "country": result.country,
                            "executed_at": result.ingested_at,
                        })
                    
                    # Insert citations
                    for c in citations:
                        conn.execute(text("""
                            INSERT INTO geo_citations
                            (report_id, request_id, task_id, result_id, client_id,
                             source_url, source_domain, source_position, source_label,
                             domain_category, is_citation_pill,
                             client_name, platform, intent, topic, product, country, executed_at)
                            VALUES (:report_id, :request_id, :task_id, :result_id, :client_id,
                                    :source_url, :source_domain, :source_position, :source_label,
                                    :domain_category, :is_citation_pill,
                                    :client_name, :platform, :intent, :topic, :product, :country, :executed_at)
                        """), {
                            "report_id": result.report_id,
                            "request_id": result.request_id,
                            "task_id": result.task_id,
                            "result_id": result.result_id,
                            "client_id": result.client_id,
                            "source_url": c["source_url"],
                            "source_domain": c["source_domain"],
                            "source_position": c.get("source_position"),
                            "source_label": c.get("source_label"),
                            "domain_category": c["domain_category"],
                            "is_citation_pill": c["is_citation_pill"],
                            "client_name": result.client_name,
                            "platform": result.platform,
                            "intent": result.intent,
                            "topic": result.topic,
                            "product": result.product,
                            "country": result.country,
                            "executed_at": result.ingested_at,
                        })
                    
                    # Mark as analyzed
                    conn.execute(text("""
                        UPDATE geo_results SET analyzed_at = NOW() WHERE result_id = :result_id
                    """), {"result_id": result_id})
                    
                    mentions_count += len(mentions)
                    citations_count += len(citations)
                
                # Commit after each batch
                conn.commit()
                total_processed += batch_count
                logger.info(f"[ANALYZER-S2] Batch committed. Total processed: {total_processed}")

            logger.info(f"[ANALYZER-S3] ========== 分析周期结束 ==========")
            logger.info(f"[ANALYZER-S3] 本次共处理 results: {total_processed}")
            logger.info(f"[ANALYZER-S3] 提取 company mentions: {mentions_count}")
            logger.info(f"[ANALYZER-S3] 提取 citations: {citations_count}")

            # 4. Check if all results for this report are analyzed
            logger.info(f"[ANALYZER-S4] 检查报告完成状态...")
            unanalyzed_count = conn.execute(text("""
                SELECT COUNT(*) FROM geo_results 
                WHERE report_id = :report_id AND analyzed_at IS NULL
            """), {"report_id": report_id}).scalar()
            
            if unanalyzed_count == 0:
                logger.info(f"[ANALYZER-S4] 所有结果已分析，更新报告状态为 completed")
                conn.execute(text("""
                    UPDATE geo_reports SET status = 'completed', updated_at = NOW() 
                    WHERE id = :report_id
                """), {"report_id": report_id})
            else:
                logger.info(f"[ANALYZER-S4] 仍有 {unanalyzed_count} 条未分析结果，保持 running 状态 (如下次运行会自动继续)")
            
            conn.commit()
            
    except Exception as e:
        logger.error(f"[ANALYZER-ERR] 分析失败: {e}")
        raise


if __name__ == "__main__":
    main()
