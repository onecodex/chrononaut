"""Test basic FlaskSQLAlchemy integration points
"""
import flask_sqlalchemy
import sqlalchemy
import pytest

import chrononaut


def test_unversioned_db_fixture(unversioned_db):
    """Test unversioned SQLAlchemy object.
    """
    assert unversioned_db.__class__ == flask_sqlalchemy.SQLAlchemy
    assert unversioned_db.session.__class__ == sqlalchemy.orm.scoping.scoped_session
    assert (unversioned_db.session.session_factory().__class__.__name__ ==
            flask_sqlalchemy.SignallingSession.__name__)


def test_db_fixture(db):
    """Test fixtures.
    """
    assert db.__class__ == chrononaut.VersionedSQLAlchemy
    assert db.session.__class__ == sqlalchemy.orm.scoping.scoped_session
    assert (db.session.session_factory().__class__.__name__ ==
            chrononaut.VersionedSignallingSession.__name__)


def test_unversioned_todo(db):
    """Test unversioned class.
    """
    todo = db.UnversionedTodo('Task 0', 'Testing...')
    assert todo.__class__ == db.UnversionedTodo


def test_versioned_todo(db, session):
    """Test basic versioning.
    """
    todo = db.Todo('Task 0', 'Testing...')
    assert todo.__class__ == db.Todo
    session.add(todo)
    session.commit()
    assert todo.versions() == []

    # Update the Task
    todo.title = 'Task 0.1'
    session.commit()

    # Update it again
    todo.title = 'Task 0.2'
    session.commit()

    # Check old versions
    prior_todos = todo.versions()
    assert len(prior_todos) == 2
    assert prior_todos[0].version == 0  # 0-based indexing
    assert prior_todos[1].version == 1
    assert prior_todos[0].title == 'Task 0'
    assert prior_todos[0].__class__.__name__ == 'TodoHistory'


def test_untracked_columns(db, session):
    """Test that changes to untracked columns are not tracked
    """
    todo = db.Todo('New Task', 'Testing...')
    session.add(todo)
    session.commit()
    assert len(todo.versions()) == 0

    # Modifying an untracked column does not change the history table
    assert todo.starred is False
    todo.starred = True
    session.commit()
    assert todo.starred is True
    assert len(todo.versions()) == 0

    # Create a version and assert that accessing the starred column fails
    todo.title = 'Newest Task'
    todo.starred = False
    session.commit()
    assert len(todo.versions()) == 1
    assert set(todo.versions()[0].change_info.keys()) == {'ip_address', 'user_id'}
    with pytest.raises(AttributeError):
        todo.versions()[0].starred
    with pytest.raises(chrononaut.exceptions.ChrononautException):
        todo.versions()[0].starred
    with pytest.raises(chrononaut.exceptions.UntrackedAttributeError):
        todo.versions()[0].starred


def test_hidden_columns(db, session):
    """Test that changes to hidden columns are tracked
    """
    todo = db.Todo('Secret Todo', 'Testing...')
    session.add(todo)
    session.commit()
    assert len(todo.versions()) == 0

    # Modifying a hidden column does change the history table
    assert todo.done is False
    todo.done = True
    session.commit()
    assert todo.done is True
    assert len(todo.versions()) == 1

    # Assert that change info is included for the hidden column
    prior_todo = todo.versions()[0]
    assert set(prior_todo.change_info['hidden_cols_changed']) == {'done'}

    # Assert multiple columns are tracked
    todo.done = False
    todo.title = 'Not Done'
    session.commit()
    last_todo = todo.versions()[-1]
    assert todo.title == 'Not Done'
    assert last_todo.title == 'Secret Todo'
    assert set(last_todo.change_info.keys()) == {'ip_address', 'user_id', 'hidden_cols_changed'}
    assert set(last_todo.change_info['hidden_cols_changed']) == {'done'}  # Only keep hidden columns

    # Accessing the hidden column from the history model fails
    with pytest.raises(AttributeError):
        last_todo.done
    with pytest.raises(chrononaut.exceptions.ChrononautException):
        last_todo.done
    with pytest.raises(chrononaut.exceptions.HiddenAttributeError):
        last_todo.done


def test_table_names(db, session):
    """Check that all expected tables are being generated,
    including custom `__chrononaut_tablename__` settings
    """
    assert (set(db.metadata.tables.keys()) ==
            {'report', 'rep_history', 'todos', 'todos_history', 'unversioned_todos',
             'appuser', 'role', 'roles_users'})


def test_change_info_no_user(db, session):
    """Test that change info is as expected without a user
    """
    todo = db.Todo('First Todo', 'Check change info')
    session.add(todo)
    session.commit()
    todo.title = 'Modified'
    session.commit()

    prior_todo = todo.versions()[0]
    assert set(prior_todo.change_info.keys()) == {'user_id', 'ip_address'}
    assert prior_todo.change_info['ip_address'] is None
    assert prior_todo.change_info['user_id'] is None


# def test_change_info(db, session, logged_in_user):
#     """Test that change info is as expected with a user
#     """
#     todo = db.Todo('First Todo', 'Check change info')
#     session.add(todo)
#     session.commit()
#     todo.title = 'Modified'
#     session.commit()

#     prior_todo = todo.versions()[0]
#     assert prior_todo.change_info['user_id'] == 'test@example.com'
