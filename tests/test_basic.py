"""Test basic FlaskSQLAlchemy integration points
"""
import sqlalchemy
import flask_sqlalchemy

import chrononaut


def test_unversioned_db_fixture(unversioned_db):
    assert unversioned_db.__class__ == flask_sqlalchemy.SQLAlchemy
    assert unversioned_db.session.__class__ == sqlalchemy.orm.scoping.scoped_session
    assert (unversioned_db.session.session_factory().__class__.__name__ ==
            flask_sqlalchemy.SignallingSession.__name__)


def test_db_fixture(db):
    assert db.__class__ == chrononaut.VersionedSQLAlchemy
    assert db.session.__class__ == sqlalchemy.orm.scoping.scoped_session
    assert (db.session.session_factory().__class__.__name__ ==
            chrononaut.VersionedSignallingSession.__name__)


def test_unversioned_todo(db):
    todo = db.UnversionedTodo('Task 0', 'Testing...')
    assert todo.__class__ == db.UnversionedTodo


def test_versioned_todo(db, session):
    todo = db.Todo('Task 0', 'Testing...')
    assert todo.__class__ == db.Todo
    session.add(todo)
    session.commit()
    assert todo.versions() == []

    # Update the Task
    todo.title = 'Task 0.1'
    session.commit()

    # Check old versions
    prior_todos = todo.versions()
    assert len(prior_todos) == 1
    assert prior_todos[0].version == 1  # 1-based indexing (!?)
    assert prior_todos[0].title == 'Task 0'
    assert prior_todos[0].__class__.__name__ == 'TodoHistory'


def test_omit_version(db, session):
    todo = db.Todo('Task 0', 'Testing...')
    session.add(todo)
    session.commit()

    assert todo.done is False
    todo.done = True
    session.commit()

    # No change in the history table, omitted columns are *never* saved
    assert len(todo.versions()) == 0

    # Now change
    todo.text = 'Done!'
    session.commit()

    # TODO: Should this throw an OmittedAttribute error of some kind? Probably...
    prior_todo = todo.versions()[0]
    assert prior_todo.done is None  # Default value
