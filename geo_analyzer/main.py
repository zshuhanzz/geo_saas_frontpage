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
            # 1. Get unanalyzed results for this report
            logger.info(f"[ANALYZER-S1] 查询未分析的 results...")
            results = conn.execute(text("""
                SELECT * FROM geo_results 
                WHERE report_id = :report_id AND analyzed_at IS NULL
            """), {"report_id": report_id}).fetchall()
            
            total = len(results)
            logger.info(f"[ANALYZER-S1] 找到 {total} 条未分析记录")
            
            if total == 0:
                logger.info("[ANALYZER-S1] 没有需要分析的数据")
                return
            
            # 2. Process each result
            mentions_count = 0
            citations_count = 0
            
            for i, result in enumerate(results):
                result_id = result.result_id
                
                # Parse company mentions
                # NOTE: Column name is 'text', not 'response_text'
                mentions = parse_company_mentions(
                    result.text or "",
                    result.client_name,
                    result.peers or []
                )
                
                # Parse citations
                # NOTE: Column names are 'sources' and 'citation_pills'
                citations = parse_citations(
                    result.sources or [],
                    result.citation_pills or [],
                    result.owned_domains or []
                )
                
                # Insert mentions
                # 实际数据库字段: id, report_id, request_id, task_id, result_id, client_id,
                #                company_name, mention_position, is_client, is_peer,
                #                client_name, platform, intent, topic, product, country, executed_at, created_at
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
                # 实际数据库字段: id, report_id, request_id, task_id, result_id, client_id,
                #                source_url, source_domain, source_position, source_label,
                #                domain_category, is_citation_pill,
                #                client_name, platform, intent, topic, product, country, executed_at, created_at
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
                
                # Progress log every 100 records
                if (i + 1) % 100 == 0:
                    logger.info(f"[ANALYZER-S2] 进度: {i + 1}/{total}")
            
            conn.commit()
            
            logger.info(f"[ANALYZER-S3] ========== 分析完成 ==========")
            logger.info(f"[ANALYZER-S3] 处理 results: {total}")
            logger.info(f"[ANALYZER-S3] 提取 company mentions: {mentions_count}")
            logger.info(f"[ANALYZER-S3] 提取 citations: {citations_count}")
            
    except Exception as e:
        logger.error(f"[ANALYZER-ERR] 分析失败: {e}")
        raise


if __name__ == "__main__":
    main()
