"""Alembic environment: the database URL comes from ASTRAL settings, never from alembic.ini."""

from alembic import context

from astral.db.models import Base
from astral.db.session import engine

target_metadata = Base.metadata


def run_migrations_online() -> None:
    with engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=connection.dialect.name == "sqlite", compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("offline migrations are not supported; run against a database")
run_migrations_online()
