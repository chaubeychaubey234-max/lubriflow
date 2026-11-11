"""Generate the initial SQL snapshot once; subsequent changes require a new migration."""

from pathlib import Path
from sqlalchemy.schema import CreateTable, CreateIndex
from sqlalchemy.dialects import postgresql
from lubriflow.models import Base

target = Path(__file__).resolve().parents[1] / "backend/migrations/versions/0001_schema.sql"
if target.exists():
    raise SystemExit("Initial schema already frozen; create a new migration for schema changes.")
dialect = postgresql.dialect()
statements = []
for table in Base.metadata.sorted_tables:
    statements.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
    for index in sorted(table.indexes, key=lambda item: item.name):
        statements.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
target.write_text("-- Immutable initial PostgreSQL schema.\n\n" + "\n\n".join(statements) + "\n")
print("Initial schema frozen:", target.name)
