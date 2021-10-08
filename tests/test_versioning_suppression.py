import pytest
from flask import g
from chrononaut.exceptions import ChrononautException
from chrononaut.unsafe import suppress_versioning


def test_cannot_delete_version_by_default(db, session):
    todo = db.SpecialTodo("Special 1", "To be deleted")
    session.add(todo)
    session.commit()

    with pytest.raises(ChrononautException):
        session.delete(todo.versions()[0])


def test_suppressing_version_info(db, session):
    todo = db.SpecialTodo("Special 1", "To be modified")
    session.add(todo)
    session.commit()

    with suppress_versioning():
        todo.title = "Some other title"
        session.commit()

        todo.text = "Modified text"
        session.commit()

    assert len(todo.versions()) == 1


def test_suppressing_version_info_delete_version_wo_flag(db, session):
    todo = db.SpecialTodo("Special 1", "A todo that's special")
    session.add(todo)
    session.commit()

    with pytest.raises(ChrononautException):
        with suppress_versioning():
            session.delete(todo.versions()[0])

    assert len(todo.versions()) == 1
    # An exception should not cause leftover attrs
    assert not hasattr(g, "__suppress_versioning__")


def test_suppressing_version_info_delete_version_commit_wo_flag(db, session):
    todo = db.SpecialTodo("Special 1", "A special todo")
    session.add(todo)
    session.commit()

    todo.title = "Some other title"
    session.commit()
    assert len(todo.versions()) == 2

    with suppress_versioning(allow_deleting_history=True):
        session.delete(todo.versions()[0])
        session.commit()
    assert len(todo.versions()) == 1


def test_suppressing_version_info_delete_version_commit_out_of_scope(db, session):
    todo = db.SpecialTodo("Special 1", "Another todo that's special")
    session.add(todo)
    session.commit()

    todo.title = "Some other title"
    session.commit()
    assert len(todo.versions()) == 2

    with suppress_versioning(allow_deleting_history=True):
        # This is fine
        session.delete(todo.versions()[0])

    # But committing out of scope if not
    with pytest.raises(ChrononautException):
        session.commit()
    session.rollback()
    assert len(todo.versions()) == 2


def test_suppressing_version_info_delete_whole_record(db, session):
    todo = db.SpecialTodo("Special 1", "A todo")
    session.add(todo)
    session.commit()

    todo.text = "Watch me disappear"
    session.commit()
    assert len(todo.versions()) == 2

    todo_id = todo.id
    with suppress_versioning(allow_deleting_history=True):
        for version in todo.versions():
            session.delete(version)
        session.delete(todo)
        session.commit()

    # No trace should be left of the object
    assert session.query(db.SpecialTodo).get(todo_id) is None
    activity_cls = db.metadata._activity_cls
    versions = (
        session.query(activity_cls)
        .filter(activity_cls.table_name == "special_todo", activity_cls.key == {"id": todo_id})
        .all()
    )
    assert len(versions) == 0
