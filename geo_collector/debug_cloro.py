
import asyncio
import httpx
import logging
import os
import json
from dotenv import load_dotenv # Import dotenv
from src.services.cloro_client import CloroService

# Load environment variables from .env file immediately
load_dotenv()

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def main():
    # Now os.getenv will work correctly if .env exists
    if not os.getenv("CLORO_API_KEY"):
        print("WARNING: CLORO_API_KEY is not set in environment or .env file.")
        print("Using 'dummy_key'. Request will likely fail with 401.")
        os.environ["CLORO_API_KEY"] = "dummy_key"
    
    # Ensure other required settings have defaults if not in .env
    os.environ.setdefault("CLORO_BASE_URL", "https://api.cloro.dev")
    os.environ.setdefault("WEBHOOK_PUBLIC_URL", "http://localhost:8080")
    os.environ.setdefault("DATABASE_URL", "postgresql://dummy")
    os.environ.setdefault("PUBSUB_PROJECT_ID", "dummy")
    os.environ.setdefault("WEBHOOK_SECRET", "dummy")

    print("\n--- Starting Cloro Client Debug (Sync Mode) ---\n")
    
    service = CloroService()
    
    # Mock task
    task = {
        "task_id": "local-debug-uuid-001",
        "platform": "chatgpt", 
        "prompt_text": "Best robot vacuums for complex home environment.",
        "country": "US"
    }
    
    print(f"Target Platform: {task['platform']}")
    print(f"Prompt: {task['prompt_text']}")
    print("Sending request... (This may take 10-30 seconds)\n")
    
    async with httpx.AsyncClient() as client:
        # Use the SYNC method for local debugging
        result = await service.dispatch_task_sync(client, task)
        
    if result:
        print("\n--- SUCCESS: Received Response ---")
        print(json.dumps(result, indent=2))
    else:
        print("\n--- FAILED: No response received ---")
        print("Check your API Key and network connection.")

if __name__ == "__main__":
    asyncio.run(main())
