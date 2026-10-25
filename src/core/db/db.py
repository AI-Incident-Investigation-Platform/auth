from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config import cfg
from src.core.db.error_translation import DatabaseErrorTranslator, TranslatingPool

engine = create_async_engine(
    cfg.database.async_database_url,
    echo=False,
    poolclass=TranslatingPool,
    pool_size=cfg.database.pool_size,
    max_overflow=cfg.database.pool_max_overflow,
    pool_timeout=cfg.database.pool_timeout_seconds,
    pool_pre_ping=True,
    pool_recycle=cfg.database.pool_recycle_seconds,
    connect_args={
        "server_settings": {
            "statement_timeout": str(cfg.database.statement_timeout_ms),
            "lock_timeout": str(cfg.database.lock_timeout_ms),
        }
    },
)

event.listen(engine.sync_engine, "do_connect", DatabaseErrorTranslator.on_connect)
event.listen(engine.sync_engine, "handle_error", DatabaseErrorTranslator.on_error, retval=True)

session_maker = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)
