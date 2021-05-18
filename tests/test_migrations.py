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

    todo = db.Todo("Todo item", "Todo text", preset_id=1)
    todo.version = 2

    alembic_op.migrate_from_history_table("todos")

    activity_cls = db.metadata._activity_cls
    assert activity_cls.query.count() == 4

    assert len(todo.versions()) == 3
    prior_todo = todo.previous_version()
    assert prior_todo.version == 1
    assert prior_todo.text == "Text without typo"

    # Test change info moved to proper snapshot version
    assert "rationale" not in prior_todo.chrononaut_meta["extra_info"]
    current_snapshot = todo.versions()[-1]
    assert current_snapshot.version == 2
    # Test extra info migration
    assert (
        current_snapshot.chrononaut_meta["extra_info"]["rationale"]
        == "Should have always been complex"
    )

    # Test user info migration
    first_version = todo.versions()[0]
    assert prior_todo.chrononaut_meta["user_info"]["user_id"] == 42
    assert prior_todo._key == {"id": 1}
    assert first_version.text == "Tpo in text"
    assert "user_id" not in first_version.chrononaut_meta["user_info"]

    # Test timestamp updates
    assert first_version.chrononaut_meta["changed"] == parse("2016-06-20 20:12:11.134125-01")
    assert current_snapshot.chrononaut_meta["changed"] == parse("2016-06-22 22:55:00.134125-01")
