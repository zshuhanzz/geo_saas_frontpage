"""
GEO Analyzer - Configuration
"""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database
    DB_USER: str = "postgres"
    DB_PASS: str = ""
    DB_NAME: str = "geo_platform"
    DB_HOST: str = "localhost"
    DB_PORT: str = "5432"
    
    # Cloud SQL (optional)
    CLOUD_SQL_CONNECTION_NAME: str = ""
    
    @property
    def database_url(self) -> str:
        """Build database URL."""
        if self.CLOUD_SQL_CONNECTION_NAME:
            # Cloud SQL with Unix socket
            return (
                f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASS}"
                f"@/{self.DB_NAME}"
                f"?host=/cloudsql/{self.CLOUD_SQL_CONNECTION_NAME}"
            )
        else:
            # Standard TCP connection
            return (
                f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASS}"
                f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            )
    
    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
