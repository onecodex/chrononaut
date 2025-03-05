"""Test basic FlaskSQLAlchemy integration points"""

import sqlalchemy

import chrononaut


def test_db_fixture(db):
    """Test fixtures."""
    assert db.__class__ == chrononaut.VersionedSQLAlchemy
    assert db.session.__class__ == sqlalchemy.orm.scoping.scoped_session
    assert (
        db.session.session_factory().__class__.__name__
        == chrononaut.VersionedSession.__name__  # noqa
    )


def test_unversioned_todo(db):
    """Test unversioned class."""
    todo = db.UnversionedTodo("Task 0", "Testing...")
    assert todo.__class__ == db.UnversionedTodo


def test_table_names(db, session):
    """Check that all expected tables are being generated,
    including custom `__chrononaut_tablename__` settings
    """
    assert set(db.metadata.tables.keys()) == {  # noqa
        "chrononaut_activity",
        "report",
        "todos",
        "unversioned_todos",
        "special_todo",
        "appuser",
        "role",
        "roles_users",
        "change_log",
    }
