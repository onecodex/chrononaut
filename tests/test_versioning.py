from datetime import datetime
import pytz

import pytest
import chrononaut


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
    assert set(todo.versions()[0].change_info.keys()) == {'remote_addr', 'user_id'}
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
    assert set(last_todo.change_info.keys()) == {'remote_addr', 'user_id', 'hidden_cols_changed'}
    assert set(last_todo.change_info['hidden_cols_changed']) == {'done'}  # Only keep hidden columns

    # Accessing the hidden column from the history model fails
    with pytest.raises(AttributeError):
        last_todo.done
    with pytest.raises(chrononaut.exceptions.ChrononautException):
        last_todo.done
    with pytest.raises(chrononaut.exceptions.HiddenAttributeError):
        last_todo.done


def test_version_fetching_and_diffing(db, session):
    time_0 = datetime.now(pytz.utc)
    todo = db.Todo('Dated Todo', 'Time 0')
    session.add(todo)
    session.commit()

    # Changes
    for ix in range(1, 10):
        todo.text = 'Time {}'.format(ix)
        session.commit()

    assert len(todo.versions()) == 9
    assert len(todo.versions(after=time_0)) == 9

    # Assert that they're ordered
    for ix, version in enumerate(todo.versions()):
        assert version.text == 'Time {}'.format(ix)

    # Make another set of changes
    time_1 = datetime.now(pytz.utc)
    todo.text = 'Time Last'
    todo.starred = True
    session.commit()

    assert len(todo.versions()) == 10
    assert len(todo.versions(before=time_1)) == 9
    assert len(todo.versions(after=time_1)) == 1
    assert len(todo.versions(after=datetime.now(pytz.utc))) == 0
    assert len(todo.versions(before=datetime.now(pytz.utc))) == 10

    # Test version_at
    first_version = todo.version_at(time_0)
    assert first_version.text == 'Time 0'
    assert first_version.__class__.__name__ == 'TodoHistory'
    ninth_version = todo.version_at(time_1)
    assert ninth_version.text == 'Time 9'
    assert ninth_version.__class__.__name__ == 'TodoHistory'
    current_version = todo.version_at(datetime.now(pytz.utc))
    assert current_version.text == 'Time Last'
    assert current_version.__class__.__name__ == 'Todo'
    assert current_version.starred is True  # untracked field

    # Test has_changed_since
    assert todo.has_changed_since(time_0) is True
    assert todo.has_changed_since(time_1) is True
    assert todo.has_changed_since(datetime.now(pytz.utc)) is False

    # Test diff logic, note the untracked column should not show up
    assert set(todo.diff(first_version).keys()) == {'text'}
    assert todo.diff(first_version)['text'] == ('Time 0', 'Time Last')
    assert todo.diff(ninth_version)['text'] == ('Time 9', 'Time Last')
    assert todo.diff(first_version, to=ninth_version)['text'] == ('Time 0', 'Time 9')

    # You can only fetch from a history model not another todo
    other_todo = db.Todo('Other Todo', 'Time -1')
    session.add(other_todo)
    session.commit()
    with pytest.raises(chrononaut.ChrononautException) as e:
        todo.diff(other_todo)
    assert e._excinfo[1].args[0] == 'You can only diff models with the same primary keys.'

    with pytest.raises(chrononaut.ChrononautException) as e:
        todo.diff(todo)
    assert e._excinfo[1].args[0] == 'Cannot diff from a non-history model.'

    # Similarly you can't diff another models history
    with pytest.raises(chrononaut.ChrononautException) as e:
        other_todo.diff(first_version)
    assert e._excinfo[1].args[0] == 'You can only diff models with the same primary keys.'

    # Nor can you fetch them out of chronological order
    with pytest.raises(chrononaut.ChrononautException) as e:
        todo.diff(ninth_version, to=first_version)
    assert e._excinfo[1].args[0].startswith('Diffs must be chronological.')

    # Diffs between the same history model *are* permitted however
    assert todo.diff(ninth_version, to=ninth_version) == {}

    # Now update a hidden column, should show with `include_hidden` option
    todo.done = True
    session.commit()
    set(todo.diff(first_version).keys()) == {'text'}
    set(todo.diff(first_version, include_hidden=True).keys()) == {'text', 'done'}
    assert todo.diff(first_version, include_hidden=True)['done'] == (None, True)
