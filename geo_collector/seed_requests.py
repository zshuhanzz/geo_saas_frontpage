"""
Seed script for geo_requests table.

Usage:
    python seed_requests.py
    python seed_requests.py --client Dyson --product "Dyson V15" --n 5 --m 3
"""
import asyncio
import uuid
import argparse
from sqlalchemy import insert
from src.core.database import database, geo_requests


async def seed_request(
    client_name: str,
    product: str,
    platform: str = "chatgpt",
    country: str = "US",
    intent: str = "Solution Discovery",
    prompts_per_request: int = 5,
    calls_per_prompt: int = 2,
    peers: str = None,
    topic: str = None,
):
    """
    Insert a test request.
    """
    request_id = str(uuid.uuid4())
    
    await database.execute(
        insert(geo_requests).values(
            request_id=request_id,
            batch_id=f"test-{request_id[:8]}",
            client_name=client_name,
            peers=peers,
            topic=topic,
            product=product,
            country=country,
            platform=platform,
            intent=intent,
            prompts_per_request=prompts_per_request,
            calls_per_prompt=calls_per_prompt,
            status="PENDING"
        )
    )
    
    print(f"✅ Created request: {request_id}")
    print(f"   Client: {client_name}")
    print(f"   Peers: {peers}")
    print(f"   Topic: {topic}")
    print(f"   Product: {product}")
    print(f"   Platform: {platform}")
    print(f"   Intent: {intent}")
    print(f"   N (prompts): {prompts_per_request}")
    print(f"   M (calls): {calls_per_prompt}")
    print(f"   Total expected results: {prompts_per_request * calls_per_prompt}")
    
    return request_id


async def main():
    parser = argparse.ArgumentParser(description="Seed geo_requests for testing")
    parser.add_argument("--client", default="RoboRock", help="Focus client name")
    parser.add_argument("--peers", default="Eufy", help="Competitor names (comma separated)")
    parser.add_argument("--topic", default="Smart Home", help="Product category")
    parser.add_argument("--product", default="robot vacuums", help="Product type")
    parser.add_argument("--platform", default="chatgpt", help="Platform (chatgpt/gemini/aimode)")
    parser.add_argument("--country", default="US", help="Country code")
    parser.add_argument("--intent", default="Solution Discovery", 
                        choices=["Solution Discovery", "Competitive Evaluation", "Specifics Inquiry"],
                        help="Intent type")
    parser.add_argument("--n", type=int, default=3, help="Number of prompts to generate")
    parser.add_argument("--m", type=int, default=2, help="Number of Cloro calls per prompt")
    
    args = parser.parse_args()
    
    await database.connect()
    try:
        await seed_request(
            client_name=args.client,
            product=args.product,
            platform=args.platform,
            country=args.country,
            intent=args.intent,
            prompts_per_request=args.n,
            calls_per_prompt=args.m,
            peers=args.peers,
            topic=args.topic,
        )
    finally:
        await database.disconnect()
    
    print("\n📋 Next steps:")
    print("   1. Run expander: python -m src.expander")
    print("   2. Pipeline will auto-trigger:")
    print("      Expander → Pub/Sub → CloroDispatcher → Cloro API → ... → ResultIngestor → DB")
    print("   3. Check results in geo_results table")


if __name__ == "__main__":
    asyncio.run(main())
