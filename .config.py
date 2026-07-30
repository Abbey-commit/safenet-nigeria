"""
SafeNet Nigeria — Environment Configuration
============================================
Central place to load and validate all environment variables.
Import this at the top of any module that needs config:

    from config import config
    print(config.ACLED_API_KEY)
    print(config.DATABASE_URL)
"""

import os

# ── Try to load .env file if python-dotenv is available ──────
try:
    from dotenv import load_dotenv
    # Walk up from this file to find .env
    _here = os.path.dirname(os.path.abspath(__file__))
    _env_path = os.path.join(_here, ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
        print(f"[Config] Loaded .env from {_env_path}")
    else:
        print(f"[Config] No .env found at {_env_path} — using system env vars")
except ImportError:
    print("[Config] python-dotenv not installed — reading system env vars directly")
    print("[Config] Install with: pip install python-dotenv")


class Config:
    """
    All environment variables in one place.
    Access anywhere: from config import config
    """

    # ── ACLED ─────────────────────────────────────────────────
    ACLED_API_KEY: str   = os.getenv("ACLED_API_KEY", "")
    ACLED_EMAIL: str     = os.getenv("ACLED_EMAIL", "")
    ACLED_DAYS_BACK: int = int(os.getenv("ACLED_DAYS_BACK", "90"))
    ACLED_COUNTRY: str   = os.getenv("ACLED_COUNTRY", "Nigeria")

    # ── DATABASE ──────────────────────────────────────────────
    DATABASE_URL: str    = os.getenv("DATABASE_URL", "")
    # If DATABASE_URL is empty, pipeline uses SQLite automatically

    # ── ENVIRONMENT ───────────────────────────────────────────
    ENVIRONMENT: str     = os.getenv("ENVIRONMENT", "development")

    # ── NOTIFICATIONS ─────────────────────────────────────────
    TERMII_API_KEY: str  = os.getenv("TERMII_API_KEY", "")
    TERMII_SENDER_ID: str= os.getenv("TERMII_SENDER_ID", "SafeNet")

    # ── SECURITY ──────────────────────────────────────────────
    SECRET_KEY: str      = os.getenv("SECRET_KEY", "dev-secret-change-in-production")

    # ── LOGGING ───────────────────────────────────────────────
    LOG_LEVEL: str       = os.getenv("LOG_LEVEL", "INFO")

    # ── Derived helpers ───────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def has_acled_credentials(self) -> bool:
        return bool(self.ACLED_API_KEY and self.ACLED_EMAIL)

    @property
    def has_database_url(self) -> bool:
        return bool(self.DATABASE_URL)

    def validate(self):
        """
        Call at startup to check critical config is present.
        Prints clear human-readable guidance if anything is missing.
        """
        print("\n[Config] Environment check:")
        print(f"  Mode        : {self.ENVIRONMENT.upper()}")

        if self.has_acled_credentials:
            print(f"  ACLED       : ✓ credentials loaded ({self.ACLED_EMAIL})")
        else:
            print(f"  ACLED       : ✗ no credentials — running in SYNTHETIC mode")
            print(f"                Register free at https://acleddata.com/register/")

        if self.has_database_url:
            print(f"  Database    : ✓ PostgreSQL ({self.DATABASE_URL[:30]}...)")
        else:
            print(f"  Database    : SQLite (dev mode) — data/safenet.db")

        if self.TERMII_API_KEY:
            print(f"  SMS alerts  : ✓ Termii configured")
        else:
            print(f"  SMS alerts  : ✗ not configured (needed for Phase 3)")

        print()


# Singleton — import this everywhere
config = Config()


if __name__ == "__main__":
    config.validate()
    print("ACLED live mode:", config.has_acled_credentials)
    print("Production mode:", config.is_production)
