import asyncio
import logging
from sqlalchemy import insert
from src.core.database import database, geo_tasks
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

async def main():
    await database.connect()
    try:
        tasks = [
            {
                "client_name": "SeedClient",
                "topic": "Smart Home",
                "product": "robot vacuums",
                "country": "US",
                "platform": "chatgpt",
                "intent": "Solution Discovery",
                "prompt_text": "Best robot vacuums for complex home environment.",
                "status": "PENDING"
            },
            {
                "client_name": "SeedClient",
                "topic": "Smart Home",
                "product": "robot vacuums",
                "country": "US",
                "platform": "gemini",
                "intent": "Solution Discovery",
                "prompt_text": "Best robot vacuum under $1000.",
                "status": "PENDING"
            },
            {
                "client_name": "SeedClient",
                "topic": "Smart Home",
                "product": "robot vacuums",
                "country": "US",
                "platform": "aimode",
                "intent": "Solution Discovery",
                "prompt_text": "Best robot vacuum under $1000.",
                "status": "PENDING"
            }
        ]
        
        await database.execute_many(insert(geo_tasks), tasks)
        logging.info(f"Inserted {len(tasks)} pending tasks.")
    finally:
        await database.disconnect()

if __name__ == "__main__":
    asyncio.run(main())