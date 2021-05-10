from sqlalchemy import text
from alembic.migration import MigrationContext
from alembic.operations import Operations
from chrononaut.migrations import MigrateFromHistoryTableOp  # noqa: F401
import pytest


@pytest.fixture(scope="function")
def alembic_op(session):
    ctx = MigrationContext.configure(session.bind)
    return Operations(ctx)


def test_migrate_history_table(db, session, alembic_op):
    sql = text(open("tests/files/seed_v0.1_db.sql", "r").read())
    session.execute(sql)

    alembic_op.migrate_from_history_table("todos")

    activity_cls = db.metadata._activity_cls
    assert activity_cls.query.count() == 3

    todo = db.Todo("Todo item", "Todo text")
    todo.id = 1  # match the history entries

    assert len(todo.versions()) == 2
    prior_todo = todo.previous_version()
    assert prior_todo.text == "Text without typo"
    assert todo.versions()[0].text == "Tpo in text"

    # Test user info migration
    assert prior_todo.chrononaut_meta["user_info"]["user_id"] == 42
    assert prior_todo._key == {"id": 1}

    # Test extra info migration
    assert (
        prior_todo.chrononaut_meta["extra_info"]["rationale"] == "Should have always been complex"
    )
