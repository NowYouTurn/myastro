import sys
import asyncio
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import pool, text # Добавлен text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Добавляем путь к проекту
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.models import Base # Импорт Base
from core.config import settings # Импорт Pydantic settings

config = context.config

# Используем URL из настроек Pydantic
DB_URL = settings.sync_database_url
if not DB_URL: raise ValueError("Sync DB URL не найден в настройках.")
config.set_main_option("sqlalchemy.url", DB_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite") # Включаем batch для SQLite
    )
    with context.begin_transaction(): context.run_migrations()

def do_run_migrations(connection):
    # Включаем batch для SQLite и в online режиме
    context.configure(connection=connection, target_metadata=target_metadata,
                      render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction(): context.run_migrations()

async def run_async_migrations():
    # Используем async URL из настроек
    connectable = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        # Включаем FK для SQLite
        if connection.dialect.name == "sqlite": await connection.execute(text("PRAGMA foreign_keys=ON"))
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online() -> None: asyncio.run(run_async_migrations())

if context.is_offline_mode(): run_migrations_offline()
else: run_migrations_online()