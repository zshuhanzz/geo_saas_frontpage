import asyncio
import logging
import json
import uuid
from datetime import datetime
from src.core.database import database, geo_tasks, geo_results
from src.worker import process_ingestion
from sqlalchemy import select, insert

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DebugIngestion")

# --- MOCK DATA ---

MOCK_TASK_ID_GPT = str(uuid.uuid4())
MOCK_TASK_ID_GEMINI = str(uuid.uuid4())
MOCK_TASK_ID_AIMODE = str(uuid.uuid4())

PAYLOAD_GPT = {
    "task": {
        "id": "cloro-task-gpt-" + str(uuid.uuid4()),
        "taskType": "CHATGPT",
        "status": "COMPLETED"
    },
    "response": {
        "text": "ChatGPT Answer",
        "html": "http://snapshot.com/gpt",
        "sources": [{"url": "http://source1.com"}],
        "shoppingCards": [{"title": "Shoe", "price": "$100"}], # Original Key
        "citationPills": [{"id": 1}],
        "map": [{"name": "Place A"}]
    }
}

PAYLOAD_GEMINI = {
    "task": {
        "id": "cloro-task-gemini-" + str(uuid.uuid4()),
        "taskType": "GEMINI",
        "status": "COMPLETED"
    },
    "response": {
        "result": { # Gemini often wraps in 'result'
            "text": "Gemini Answer",
            "html": "http://snapshot.com/gemini",
            "sources": [{"url": "http://source2.com"}]
        }
    }
}

PAYLOAD_AIMODE = {
    "task": {
        "id": "cloro-task-aimode-" + str(uuid.uuid4()),
        "taskType": "AIMODE",
        "status": "COMPLETED"
    },
    "response": {
        "result": {
            "text": "AI Mode Answer",
            "places": [{"name": "Place B"}],
            "shopping_cards": [{"title": "Laptop", "price": "$1000"}] # snake_case
        }
    }
}

# --- TEST LOGIC ---

async def seed_tasks():
    """Create PENDING tasks in DB to simulate dispatch."""
    logger.info("Seeding Mock Tasks...")
    async with database.transaction():
        # GPT Task
        await database.execute(insert(geo_tasks).values(
            task_id=MOCK_TASK_ID_GPT,
            client_name="TestClient",
            country="US",
            platform="chatgpt",
            prompt_text="Test GPT",
            status="PENDING"
        ))
        # Gemini Task
        await database.execute(insert(geo_tasks).values(
            task_id=MOCK_TASK_ID_GEMINI,
            client_name="TestClient",
            country="US",
            platform="gemini",
            prompt_text="Test Gemini",
            status="PENDING"
        ))
        # AI Mode Task
        await database.execute(insert(geo_tasks).values(
            task_id=MOCK_TASK_ID_AIMODE,
            client_name="TestClient",
            country="US",
            platform="aimode",
            prompt_text="Test AI Mode",
            status="PENDING"
        ))
    logger.info("Seeding Complete.")

async def run_ingestion_test():
    await database.connect()
    
    try:
        # 1. Seed Tasks
        await seed_tasks()
        
        # 2. Process Ingestion (Calling Worker Logic Directly)
        logger.info("--- Testing ChatGPT Ingestion ---")
        # Inject task_id into payload as worker expects it from the Pub/Sub message structure if needed, 
        # but process_ingestion takes task_id as arg.
        # However, our worker extracts logic might rely on payload content?
        # Let's check worker signature: process_ingestion(task_id, payload)
        await process_ingestion(MOCK_TASK_ID_GPT, PAYLOAD_GPT)
        
        logger.info("--- Testing Gemini Ingestion ---")
        await process_ingestion(MOCK_TASK_ID_GEMINI, PAYLOAD_GEMINI)
        
        logger.info("--- Testing AI Mode Ingestion ---")
        await process_ingestion(MOCK_TASK_ID_AIMODE, PAYLOAD_AIMODE)
        
        # 3. Verify DB Content
        logger.info("--- Verifying DB Content ---")
        
        # Check GPT
        row_gpt = await database.fetch_one(
            select(geo_results).where(geo_results.c.task_id == MOCK_TASK_ID_GPT)
        )
        assert row_gpt is not None
        mock_sc = json.loads(row_gpt['shopping_cards']) if isinstance(row_gpt['shopping_cards'], str) else row_gpt['shopping_cards']
        # Note: JSONB usually returns dict/list in asyncpg, but let's be safe.
        logger.info(f"GPT Shopping Cards (Unpacked): {mock_sc}")
        assert mock_sc[0]['price'] == "$100"
        logger.info("GPT Verification PASSED")

        # Check Gemini
        row_gemini = await database.fetch_one(
            select(geo_results).where(geo_results.c.task_id == MOCK_TASK_ID_GEMINI)
        )
        assert row_gemini is not None
        logger.info(f"Gemini Text (Unpacked): {row_gemini['text']}")
        assert row_gemini['text'] == "Gemini Answer"
        logger.info("Gemini Verification PASSED")
        
        # Check AI Mode
        row_aimode = await database.fetch_one(
            select(geo_results).where(geo_results.c.task_id == MOCK_TASK_ID_AIMODE)
        )
        assert row_aimode is not None
        mock_places = row_aimode['places']
        logger.info(f"AI Mode Places (Unpacked): {mock_places}")
        assert mock_places[0]['name'] == "Place B"
        logger.info("AI Mode Verification PASSED")
        
    except Exception as e:
        logger.error(f"Test Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup? 
        # await database.execute(delete(geo_tasks).where(geo_tasks.c.task_id.in_([...])))
        await database.disconnect()

if __name__ == "__main__":
    asyncio.run(run_ingestion_test())
