from datetime import datetime, timedelta
from chrononaut import extra_change_info
from chrononaut.flask_versioning import UTC


def _prepare_todo(db, init_title, init_text, new_title):
    todo = db.Todo(init_title, init_text)
    db.session.add(todo)
    db.session.commit()
    todo.title = new_title
    db.session.commit()
    return todo


def test_change_info_no_user(db):
    """Test that change info is as expected without a user"""
    todo = _prepare_todo(db, "First Todo", "Check change info", "Modified")

    assert len(todo.versions()) == 2
    assert todo.version == 1
    prior_todo = todo.versions()[0]
    assert set(prior_todo.chrononaut_meta["user_info"].keys()) == {"user_id", "remote_addr"}
    assert prior_todo.chrononaut_meta["user_info"]["remote_addr"] is None
    assert prior_todo.chrononaut_meta["user_info"]["user_id"] is None


def test_change_info_anonymous_user(db, anonymous_user):
    todo = _prepare_todo(db, "Anonymous Todo", "Expect no user id", "Modified")
    assert todo.versions()[1].chrononaut_meta["user_info"]["user_id"] is None


def test_change_info(db, logged_in_user):
    """Test that change info is as expected with a user"""
    todo = _prepare_todo(db, "First Todo", "Check change info", "Modified")
    assert len(todo.versions()) == 2
    prior_todo = todo.versions()[1]
    assert prior_todo.chrononaut_meta["user_info"]["user_id"] == "test@example.com"
    assert prior_todo.chrononaut_meta["user_info"]["remote_addr"] == "10.0.0.1"
    assert not prior_todo.chrononaut_meta["extra_info"]


def test_custom_change_info(db, extra_change_info):
    todo = _prepare_todo(db, "First Todo", "Check change info", "Modified")
    assert len(todo.versions()) == 2
    prior_todo = todo.versions()[1]
    assert "extra_field" in prior_todo.chrononaut_meta["extra_info"]
    assert prior_todo.chrononaut_meta["extra_info"]["extra_field"] is True


def test_change_info_mixin(db, logged_in_user):
    note = db.ChangeLog(note="Creating a new change note...")
    with extra_change_info(comment="Adding a note from test function"):
        db.session.add(note)
        db.session.commit()
    assert note.change_info["user_id"] == "test@example.com"
    assert note.change_info["remote_addr"] == "10.0.0.1"
    assert (datetime.now(UTC) - note.changed).total_seconds() < 1
    assert note.version == 0
    assert note.versions() == [note.version_at(datetime.now(UTC))]

    # Now make a change
    note.note = "Updating our note"
    db.session.commit()

    # Also check that versions query works
    now = datetime.now(UTC)
    before_test = now - timedelta(60)
    assert note.version == 1
    assert len(note.versions(before=now)) == 2
    assert len(note.versions(before=before_test)) == 0
    assert len(note.versions(after=now)) == 0
