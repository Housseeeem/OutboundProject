from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/agentic"
    REDIS_URL: str = "redis://localhost:6379"
    GRAPH_DB_URL: str = "neo4j://localhost:7687"
    GRAPH_DB_USER: str = "neo4j"
    GRAPH_DB_PASSWORD: str = "password"
    GEMINI_API_KEY: str = ""
    AGENT_MODEL: str = "gemini-2.5-flash"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    OPENAI_MODEL: str = ""
    OPENAI_VERIFY_TLS: bool = True
    AGENT_RUN_RETENTION_DAYS: int = 30

    # External agent endpoints (A2A command plane)
    DETECTIVE_A2A_URL: str = "http://detective:8002"
    WRITER_A2A_URL: str = "http://writer:8003"

    INGEST_MAX_INFLIGHT: int = 64
    INGEST_BACKPRESSURE_RETRY_AFTER_SECONDS: int = 2
    INGEST_DUPLICATE_WINDOW_SECONDS: int = 5
    INGEST_DB_TIMEOUT_SECONDS: int = 3
    EVENT_SCHEMA_VALIDATION_MODE: str = "warn"
    EVENT_SCHEMA_ALLOW_UNKNOWN_TYPES: bool = True
    OUTCOME_LINK_REQUIRES_EVENT: bool = False
    OPTIMIZATION_APPLY_ENABLED: bool = True
    OPTIMIZATION_APPLY_DISABLED_RECOMMENDATION_TYPES: list[str] = []
    OPTIMIZATION_APPLY_MAX_CHANGE_PCT: float = 10.0
    OPTIMIZATION_APPLY_ALLOWED_ACTIONS: list[str] = [
        "increase_variant_share",
        "refresh_subject_lines",
        "adjust_followup_threshold",
        "prioritize_high_intent_segments",
    ]
    OPTIMIZATION_APPLY_ALLOWED_TARGET_SCOPES: list[str] = ["all", "high_intent_segments"]
    AGENT_SQL_ALLOWLIST: list[str] = [
        "SELECT COUNT(*) FROM events;",
        "SELECT event_type, COUNT(*) FROM events GROUP BY event_type;",
        "SELECT * FROM events WHERE event_type = $1 LIMIT 10;",
    ]

    model_config = SettingsConfigDict(
        env_file=("WorkerModule/.env", ".env"),  # works from workspace root or WorkerModule/
        extra="ignore"
    )


settings = Settings()
