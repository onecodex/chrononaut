"""Test basic FlaskSQLAlchemy integration points
"""
import flask_sqlalchemy
import sqlalchemy

import chrononaut


def test_unversioned_db_fixture(unversioned_db):
    """Test unversioned SQLAlchemy object."""
    assert unversioned_db.__class__ == flask_sqlalchemy.SQLAlchemy
    assert unversioned_db.session.__class__ == sqlalchemy.orm.scoping.scoped_session
    assert (
        unversioned_db.session.session_factory().__class__.__name__
        == flask_sqlalchemy.SignallingSession.__name__  # noqa
    )


def test_db_fixture(db):
    """Test fixtures."""
    assert db.__class__ == chrononaut.VersionedSQLAlchemy
    assert db.session.__class__ == sqlalchemy.orm.scoping.scoped_session
    assert (
        db.session.session_factory().__class__.__name__
        == chrononaut.VersionedSignallingSession.__name__  # noqa
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
        "activity",
        "report",
        "todos",
        "unversioned_todos",
        "special_todo",
        "appuser",
        "role",
        "roles_users",
        "change_log",
    }
