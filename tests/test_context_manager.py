from flask import current_app
from chrononaut import append_change_info, extra_change_info, rationale
import chrononaut

import pytest


def test_extra_change_info(db, session):
    """Test that the `extra_change_info` context manager
    works when it wraps a `session.commit()` call
    """
    todo = db.Todo("Task 0", "Testing...")
    session.add(todo)
    session.commit()

    with extra_change_info(reason="The commit *must* be in the block."):
        todo.title = "Task -1"
        session.commit()

    assert (
        todo.versions()[1].chrononaut_meta["extra_info"]["reason"]
        == "The commit *must* be in the block."
    )

    with extra_change_info(reason="Other no change info is recorded."):
        todo.title = "Task -2"
    session.commit()

    assert "reason" not in todo.versions()[2].chrononaut_meta["extra_info"].keys()


def test_append_change_info(db, session):
    todo = db.Todo("Task 0", "Append direct")
    session.add(todo)
    session.commit()

    with append_change_info(todo, reason="Extra object info"):
        todo.title = "Task -1"

    # Commit does *not* need to be in the block
    session.commit()

    assert todo.versions()[1].chrononaut_meta["extra_info"]["reason"] == "Extra object info"


def test_unstrict_session(db, session):
    assert current_app.config.get("CHRONONAUT_REQUIRE_EXTRA_CHANGE_INFO", False) is False


def test_strict_session(db, session, strict_session):
    assert current_app.config.get("CHRONONAUT_REQUIRE_EXTRA_CHANGE_INFO", False) is True

    todo = db.Todo("Task 0", "Strict!")

    # Inserting a record raises an exception
    with pytest.raises(chrononaut.exceptions.ChrononautException):
        session.add(todo)
        session.commit()
    session.rollback()

    # Unless wrapped in extra_change_info
    with extra_change_info(reason="Inserting a record with change info"):
        session.add(todo)
        session.commit()

    # Subsequent changes should raise an error
    with pytest.raises(chrononaut.exceptions.ChrononautException):
        todo.title = "Updated"
        session.commit()
    session.rollback()

    # Unless wrapped in extra_change_info
    with extra_change_info(reason="Because I wanted to edit this record!"):
        todo.title = "Updated"
        session.commit()
    assert todo.title == "Updated"


def test_rationale(db, session):
    todo = db.Todo("Task 0", "Do it.")
    session.add(todo)
    session.commit()

    todo.title = "Updated for testing..."
    with rationale("For testing!"):
        session.commit()
    assert todo.versions()[1].chrononaut_meta["extra_info"]["rationale"] == "For testing!"
