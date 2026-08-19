"""env.py — configuração de ambiente do Alembic para o cockpit.

O URL do banco vem da variável DATABASE_URL (PSQL estilo SQLAlchemy, ex.:
`postgresql+psycopg://cockpit:cockpit@db:5432/cockpit`). Sem a variável, usa o
padrão da stack de demonstração (docker-compose.cockpit.yml).
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://cockpit:cockpit@localhost:5432/cockpit",
)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Sem domínio por enquanto — primeira migration é só marcadora. Quando houver
# modelos, apontar aqui: target_metadata = Base.metadata
target_metadata = None


def run_migrations_offline() -> None:
    """Modo offline: emite SQL sem tocar no banco."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modo online: conecta no banco e executa as migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()