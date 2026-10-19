from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config import cfg
from src.core.db.error_translation import DatabaseErrorTranslator

engine = create_async_engine(
    cfg.database.async_database_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
)

event.listen(engine.sync_engine, "do_connect", DatabaseErrorTranslator.on_connect)
event.listen(engine.sync_engine, "handle_error", DatabaseErrorTranslator.on_error, retval=True)

session_maker = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)
