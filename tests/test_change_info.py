from datetime import datetime, timedelta
from chrononaut import extra_change_info
from chrononaut.flask_versioning import UTC


def test_change_info_no_user(db, session):
    """Test that change info is as expected without a user"""
    todo = db.Todo("First Todo", "Check change info")
    session.add(todo)
    session.commit()
    todo.title = "Modified"
    session.commit()

    assert len(todo.versions()) == 2
    assert todo.version == 1
    prior_todo = todo.versions()[0]
    assert set(prior_todo.chrononaut_meta["user_info"].keys()) == {"user_id", "remote_addr"}
    assert prior_todo.chrononaut_meta["user_info"]["remote_addr"] is None
    assert prior_todo.chrononaut_meta["user_info"]["user_id"] is None


def test_change_info_anonymous_user(db, session, anonymous_user):
    todo = db.Todo("Anonymous Todo", "Expect no user id")
    session.add(todo)
    session.commit()
    todo.title = "Modified"
    session.commit()
    assert todo.versions()[1].chrononaut_meta["user_info"]["user_id"] is None


def test_change_info(db, session, logged_in_user):
    """Test that change info is as expected with a user"""
    todo = db.Todo("First Todo", "Check change info")
    session.add(todo)
    session.commit()
    todo.title = "Modified"
    session.commit()

    assert len(todo.versions()) == 2
    prior_todo = todo.versions()[1]
    assert prior_todo.chrononaut_meta["user_info"]["user_id"] == "test@example.com"
    assert prior_todo.chrononaut_meta["user_info"]["remote_addr"] == "127.0.0.1"
    assert not prior_todo.chrononaut_meta["extra_info"]


def test_custom_change_info(db, session, extra_change_info):
    todo = db.Todo("First Todo", "Check change info")
    session.add(todo)
    session.commit()
    todo.title = "Modified"
    session.commit()

    assert len(todo.versions()) == 2
    prior_todo = todo.versions()[1]
    assert "extra_field" in prior_todo.chrononaut_meta["extra_info"]
    assert prior_todo.chrononaut_meta["extra_info"]["extra_field"] is True


def test_change_info_mixin(db, session, logged_in_user):
    note = db.ChangeLog(note="Creating a new change note...")
    with extra_change_info(comment="Adding a note from test function"):
        session.add(note)
        session.commit()
    assert note.change_info["user_id"] == "test@example.com"
    assert note.change_info["remote_addr"] == "127.0.0.1"
    assert (datetime.now(UTC) - note.changed).total_seconds() < 1
    print([str(x) for x in note.versions()])
    print(str(note.version_at(datetime.now(UTC), return_snapshot=True)))
    assert note.version == 0
    assert note.versions() == [note.version_at(datetime.now(UTC))]

    # Now make a change
    note.note = "Updating our note"
    session.commit()

    # Also check that versions query works
    now = datetime.now(UTC)
    before_test = now - timedelta(60)
    assert note.version == 1
    assert len(note.versions(before=now)) == 2
    assert len(note.versions(before=before_test)) == 0
    assert len(note.versions(after=now)) == 0
