"""
SafeNet Nigeria — Environment Configuration
Central place to load all environment variables.
Import anywhere: from config import config
"""

import os

try:
    from dotenv import load_dotenv
    _env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(_env):
        load_dotenv(_env)
        print(f"[Config] Loaded .env")
    else:
        print("[Config] Using Codespaces secrets / system env vars")
except ImportError:
    print("[Config] python-dotenv not installed — using system env vars")


class Config:
    ACLED_EMAIL:     str = os.getenv("ACLED_EMAIL",    "")
    ACLED_PASSWORD:  str = os.getenv("ACLED_PASSWORD", "")
    ACLED_DAYS_BACK: int = int(os.getenv("ACLED_DAYS_BACK", "90"))
    ACLED_COUNTRY:   str = os.getenv("ACLED_COUNTRY",  "Nigeria")
    DATABASE_URL:    str = os.getenv("DATABASE_URL",   "")
    ENVIRONMENT:     str = os.getenv("ENVIRONMENT",    "development")
    TERMII_API_KEY:  str = os.getenv("TERMII_API_KEY", "")
    SECRET_KEY:      str = os.getenv("SECRET_KEY",     "dev-secret")
    LOG_LEVEL:       str = os.getenv("LOG_LEVEL",      "INFO")

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def has_acled_credentials(self) -> bool:
        return bool(self.ACLED_EMAIL and self.ACLED_PASSWORD)

    def validate(self):
        print("\n[Config] Environment check:")
        print(f"  Mode     : {self.ENVIRONMENT.upper()}")
        if self.has_acled_credentials:
            print(f"  ACLED    : credentials loaded ({self.ACLED_EMAIL})")
        else:
            print(f"  ACLED    : no credentials — running in SYNTHETIC mode")
        if self.DATABASE_URL:
            print(f"  Database : PostgreSQL")
        else:
            print(f"  Database : SQLite (dev mode)")
        print()


config = Config()

if __name__ == "__main__":
    config.validate()
    print("ACLED ready:", config.has_acled_credentials)
