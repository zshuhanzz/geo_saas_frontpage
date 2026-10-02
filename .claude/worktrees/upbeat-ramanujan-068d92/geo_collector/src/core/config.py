import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Optional

class Settings(BaseSettings):
    # --- Database Configuration ---
    # Optional: Can be set directly, or constructed dynamically below
    DATABASE_URL: Optional[str] = None
    
    # Components for dynamic construction
    DB_INSTANCE_CONNECTION_NAME: Optional[str] = None
    DB_NAME: str = "answer-x-geo-db"
    DB_USER: str = "answer-x-geo-db-user"
    DB_PASSWORD: str
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    
    # --- Cloro API Configuration ---
    CLORO_API_KEY: str
    CLORO_BASE_URL: str = "https://api.cloro.dev"
    
    # --- Google Cloud Pub/Sub Configuration ---
    PUBSUB_PROJECT_ID: str
    PUBSUB_CALLBACKS_TOPIC: str = "geo-cloro-callbacks"  # Cloro callback results
    PUBSUB_TASKS_TOPIC: str = "geo-tasks-pending"        # Tasks ready for dispatch
    
    # --- Webhook Configuration ---
    WEBHOOK_PUBLIC_URL: str
    WEBHOOK_SECRET: Optional[str] = None  # Changed to Optional as it's not currently used
    
    # --- App Settings ---
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    
    # --- Vertex AI (Gemini) Configuration ---
    GCP_PROJECT_ID: Optional[str] = None
    GCP_REGION: str = "us-central1"
    GEMINI_MODEL_ID: str = "gemini-2.5-flash"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def model_post_init(self, __context):
        """
        Dynamically construct DATABASE_URL based on environment.
        """
        if not self.DATABASE_URL:
            # Check if running in Cloud Run (K_SERVICE is auto-set by Services, IS_CLOUD_RUN can be manually set for Jobs)
            is_cloud_run = os.environ.get("K_SERVICE") or os.environ.get("IS_CLOUD_RUN")
            
            # URL Encode password to handle special characters safely
            import urllib.parse
            encoded_password = urllib.parse.quote_plus(self.DB_PASSWORD)
            
            if is_cloud_run and self.DB_INSTANCE_CONNECTION_NAME:
                # Cloud Run: Use Unix Socket
                # Note: asyncpg uses a slightly different format for unix sockets than psycopg2
                # Format: postgresql+asyncpg://user:pass@/dbname?host=/cloudsql/INSTANCE_CONNECTION_NAME
                socket_dir = f"/cloudsql/{self.DB_INSTANCE_CONNECTION_NAME}"
                self.DATABASE_URL = (
                    f"postgresql+asyncpg://{self.DB_USER}:{encoded_password}@/{self.DB_NAME}"
                    f"?host={socket_dir}"
                )
            else:
                # Local: Use TCP
                self.DATABASE_URL = (
                    f"postgresql+asyncpg://{self.DB_USER}:{encoded_password}@"
                    f"{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
                )

@lru_cache
def get_settings():
    return Settings()