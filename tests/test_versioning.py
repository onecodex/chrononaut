from chrononaut.flask_versioning import serialize_datetime, UTC
from datetime import datetime

import pytest
import chrononaut


def test_versioned_todo(db, session):
    """Test basic versioning."""
    todo = db.Todo("Task 0", "Testing...")
    assert todo.__class__ == db.Todo
    session.add(todo)
    session.commit()
    assert todo.versions() == [todo.version_at(datetime.now(UTC))]

    # Update the Task
    todo.title = "Task 0.1"
    session.commit()

    # Update it again
    todo.title = "Task 0.2"
    session.commit()

    # Check old versions
    prior_todos = todo.versions()
    assert len(prior_todos) == 3
    prior_title = prior_todos[0].title

    assert prior_todos[0].version == 0  # 0-based indexing
    assert prior_todos[1].version == 1
    assert prior_todos[2].version == 2
    assert prior_title == "Task 0"
    assert prior_todos[0].__class__.__name__ == "HistorySnapshot"


def test_model_changes(db, session):
    todo_text = "Rule the world"
    todo = db.Todo("Todo #1", todo_text)
    session.add(todo)
    session.commit()

    time_0 = datetime.now(UTC)

    # Create original model snapshot
    todo.title = "Todo #2"
    session.commit()

    # Column `text` becomes untracked
    untracked = getattr(todo, "__chrononaut_untracked__", [])
    setattr(todo, "__chrononaut_untracked__", untracked + ["text"])

    todo.title = "Todo #3"
    session.commit()

    diff = todo.diff(time_0)
    assert "text" in diff
    assert diff["text"] == (todo_text, None)

    # Column `starred` becomes tracked
    untracked = getattr(todo, "__chrononaut_untracked__", [])
    untracked.remove("starred")
    setattr(todo, "__chrononaut_untracked__", untracked)

    todo.title = "Todo #4"
    session.commit()

    diff = todo.diff(time_0)
    assert "starred" in diff
    assert diff["starred"] == (None, False)


def test_previous_version_not_modifiable(db, session):
    todo = db.Todo("Task 0", "Testing...")
    session.add(todo)
    session.commit()
    assert todo.versions() == [todo.version_at(datetime.now(UTC))]

    todo.title = "Task 0.1"
    session.commit()
    todo.title = "Task 0.2"
    session.commit()

    prior_task = todo.previous_version()

    with pytest.raises(chrononaut.ChrononautException) as e:
        prior_task.title = "Branching history todo title"
    assert e._excinfo[1].args[0] == "Cannot modify a HistorySnapshot model."

    with pytest.raises(chrononaut.ChrononautException) as e:
        del prior_task.title
    assert e._excinfo[1].args[0] == "Cannot modify a HistorySnapshot model."


def test_delete_tracking(db, session):
    todo = db.SpecialTodo("Special 1", "To be deleted")
    session.add(todo)
    session.commit()
    session.delete(todo)
    session.commit()
    assert len(todo.versions()) == 2


def test_versioning_enum_columns(db, session):
    todo = db.Todo("Task 0.1", "Testing...")
    todo.priority = db.Priority.HIGH
    session.add(todo)
    session.commit()
    todo.title = "Task 0.2"
    session.commit()

    assert len(todo.versions()) == 2
    prior_todo = todo.previous_version()
    assert prior_todo.priority == str(db.Priority.HIGH)


def test_versioning_datetime_columns(db, session):
    timestamp = datetime.now(UTC)
    todo = db.Todo("Task 0.1", "Testing...")
    todo.pub_date = timestamp
    session.add(todo)
    session.commit()
    todo.title = "Task 0.2"
    session.commit()

    assert len(todo.versions()) == 2
    prior_todo = todo.previous_version()
    assert prior_todo.pub_date == serialize_datetime(timestamp)


def test_untracked_columns(db, session):
    """Test that changes to untracked columns are not tracked"""
    todo = db.Todo("New Task", "Testing...")
    session.add(todo)
    session.commit()
    assert len(todo.versions()) == 1

    # Modifying an untracked column does not change the history table
    assert todo.starred is False
    todo.starred = True
    session.commit()
    assert todo.starred is True
    assert len(todo.versions()) == 1

    # Create a version and assert that accessing the starred column fails
    todo.title = "Newest Task"
    todo.starred = False
    session.commit()
    assert len(todo.versions()) == 2
    assert set(todo.versions()[1].chrononaut_meta["user_info"].keys()) == {"remote_addr", "user_id"}
    assert "starred" not in todo.versions()[1]._data

    # Accessing the untracked column from a historic model raises an exception
    prior_todo = todo.previous_version()
    with pytest.raises(AttributeError):
        prior_todo.starred
    with pytest.raises(chrononaut.exceptions.UntrackedAttributeError):
        prior_todo.starred


def test_hidden_columns(db, session):
    """Test that changes to hidden columns are tracked"""
    todo = db.Todo("Secret Todo", "Testing...")
    session.add(todo)
    session.commit()
    assert len(todo.versions()) == 1

    # Modifying a hidden column does change the history table
    assert todo.done is False
    todo.done = True
    session.commit()
    assert todo.done is True
    assert len(todo.versions()) == 2

    # Assert that change info is included for the hidden column
    prior_todo = todo.versions()[1]
    print(prior_todo.chrononaut_meta["extra_info"]["hidden_cols_changed"])
    assert set(prior_todo.chrononaut_meta["extra_info"]["hidden_cols_changed"]) == {"done"}

    # Assert multiple columns are tracked
    todo.done = False
    todo.title = "Not Done"
    session.commit()
    last_todo = todo.versions()[-1]
    assert todo.title == "Not Done"
    assert last_todo.title == "Not Done"
    todo.versions()[-2].title == "Secret Todo"
    assert set(last_todo.chrononaut_meta["user_info"].keys()) == {"remote_addr", "user_id"}
    assert set(last_todo.chrononaut_meta["extra_info"].keys()) == {"hidden_cols_changed"}
    # Only keep hidden columns
    assert set(last_todo.chrononaut_meta["extra_info"]["hidden_cols_changed"]) == {"done"}

    prior_todo = todo.previous_version()
    # Accessing the hidden column from the history model fails
    with pytest.raises(AttributeError):
        prior_todo.done
    with pytest.raises(chrononaut.exceptions.HiddenAttributeError):
        prior_todo.done


def test_versioning_relationships(db, session, logged_in_user):
    user = db.User.query.first()
    role = db.Role.query.first()
    assert user is not None
    assert role is not None
    user.email = "changed_address@example.com"
    assert len(user.roles) == 0
    user.roles.append(role)
    user.primary_role = role
    session.commit()

    # Relationships are *not* currently versioned, but IDs are
    assert user.versions()[0]._data.get("roles") is None

    # But other relationships work via the foreign key column
    assert user.primary_role == role
    assert user.versions()[0]._data.get("primary_role_id") is None

    # But not the relationship itself
    with pytest.raises(AttributeError):
        user.previous_version().primary_role


def test_version_fetching_and_diffing(db, session):
    time_0 = datetime.now(UTC)
    todo = db.Todo("Dated Todo", "Time 0")
    session.add(todo)
    session.commit()

    time_1 = datetime.now(UTC)

    # Changes
    for ix in range(1, 10):
        todo.text = "Time {}".format(ix)
        session.commit()

    assert len(todo.versions()) == 10
    assert len(todo.versions(after=time_0)) == 10

    # Assert that they're ordered
    for ix, version in enumerate(todo.versions()):
        assert version.text == "Time {}".format(ix)

    # Make another set of changes
    time_2 = datetime.now(UTC)
    todo.text = "Time Last"
    todo.starred = True
    session.commit()

    assert len(todo.versions()) == 11
    assert len(todo.versions(before=time_2)) == 10
    assert len(todo.versions(after=time_2)) == 1
    assert len(todo.versions(after=datetime.now(UTC))) == 0
    assert len(todo.versions(before=datetime.now(UTC))) == 11

    # Test version_at
    assert todo.version_at(time_0) is None
    first_version = todo.version_at(time_1)
    assert first_version.text == "Time 0"
    assert first_version.__class__.__name__ == "HistorySnapshot"
    ninth_version = todo.version_at(time_2)
    assert ninth_version.text == "Time 9"
    assert ninth_version.__class__.__name__ == "HistorySnapshot"
    current_version = todo.version_at(datetime.now(UTC))
    assert current_version.text == "Time Last"
    assert current_version.__class__.__name__ == "HistorySnapshot"
    with pytest.raises(AttributeError):
        current_version.starred  # untracked field

    # Test has_changed_since
    assert todo.has_changed_since(time_0) is True
    assert todo.has_changed_since(time_2) is True
    assert todo.has_changed_since(datetime.now(UTC)) is False

    # Test diff logic, note the untracked column should not show up
    assert set(todo.diff(time_0).keys()) == {
        "created_at",
        "id",
        "title",
        "todo_type",
        "priority",
        "pub_date",
        "text",
        "version",
    }
    assert todo.diff(time_1)["text"] == ("Time 0", "Time Last")
    assert todo.diff(time_2)["text"] == ("Time 9", "Time Last")
    assert todo.diff(time_1, to_timestamp=time_2)["text"] == ("Time 0", "Time 9")

    # You can only compare based on timestamps, not objects
    other_todo = db.Todo("Other Todo", "Time -1")
    session.add(other_todo)
    session.commit()
    with pytest.raises(chrononaut.ChrononautException) as e:
        todo.diff(other_todo)
    assert e._excinfo[1].args[0] == "The diff method takes datetime as its argument."

    # You cannot diff out of chronological order
    with pytest.raises(chrononaut.ChrononautException) as e:
        todo.diff(time_2, to_timestamp=time_0)
    assert e._excinfo[1].args[0].startswith("Diffs must be chronological.")

    # Diffs between the same history model *are* permitted however
    assert todo.diff(time_2, to_timestamp=time_2) == {}

    # Now update a hidden column, should show with `include_hidden` option
    todo.done = True
    session.commit()
    set(todo.diff(time_0).keys()) == {"text"}
    set(todo.diff(time_0, include_hidden=True).keys()) == {"text", "done"}
    assert todo.diff(time_0, include_hidden=True)["done"] == (None, True)
