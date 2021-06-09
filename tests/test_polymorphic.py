from chrononaut.flask_versioning import UTC
from datetime import datetime
from sqlalchemy import text
from alembic.migration import MigrationContext
from alembic.operations import Operations
from chrononaut.migrations import MigrateFromHistoryTableOp  # noqa: F401
from dateutil.parser import parse
import pytest


@pytest.fixture(scope="function")
def alembic_op(session):
    ctx = MigrationContext.configure(session.bind)
    return Operations(ctx)


def test_migrate_history_table(db, session, alembic_op):
    sql = text(open("tests/files/seed_v0.1_db.sql", "r").read())
    session.execute(sql)

    todo = db.SpecialTodo("Todo item", "Todo text", preset_id=42)
    todo.version = 1

    alembic_op.migrate_from_history_table("special_todo")

    activity_cls = db.metadata._activity_cls
    assert activity_cls.query.count() == 2

    assert len(todo.versions()) == 2
    prior_todo = todo.previous_version()
    assert prior_todo.version == 0
    assert prior_todo.text == "Typo in title"

    # Test timestamp updates
    first_version = todo.versions()[0]
    current_snapshot = todo.versions()[-1]
    assert first_version.chrononaut_meta["changed"] == parse("2016-06-11 21:37:01.123456-01")
    assert current_snapshot.chrononaut_meta["changed"] == parse("2016-06-11 21:42:42.123457-01")

    # Testing if base columns are saved
    time_0 = datetime.now(UTC)
    existing = db.session.get(db.SpecialTodo, 42)
    existing.title = "New title #1"
    db.session.commit()

    assert existing.diff(time_0)["title"] == ("Special Todo #1", "New title #1")
