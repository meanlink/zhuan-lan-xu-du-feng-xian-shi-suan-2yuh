from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models

# Lightweight additive migration for SQLite/MySQL. Existing rows keep working:
# standard batches/jobs are backfilled to their pre-blind behaviour.
ADDED_COLUMNS = {
    'datasets': {
        'kind': "VARCHAR(20) NOT NULL DEFAULT 'standard'",
        'case_id': 'INTEGER NULL',
    },
    'jobs': {
        'artifact': 'JSON NULL',
        'scope': "VARCHAR(20) NOT NULL DEFAULT 'standard'",
        'case_id': 'INTEGER NULL',
        'attempts': 'INTEGER NOT NULL DEFAULT 1',
    },
}


def _add_columns():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, columns in ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {c['name'] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in present:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))


def migrate():
    Base.metadata.create_all(engine)
    _add_columns()


if __name__ == '__main__':
    migrate()
