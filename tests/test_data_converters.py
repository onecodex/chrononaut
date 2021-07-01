from chrononaut.data_converters import HistoryModelDataConverter
from sqlalchemy import text
from dateutil.parser import parse
from chrononaut.flask_versioning import UTC
from datetime import datetime


def test_convert_model_polymorphic(db, session):
    sql = text(open("tests/files/seed_v0.1_db.sql", "r").read())
    session.execute(sql)
    session.commit()

    converter = HistoryModelDataConverter(db.SpecialTodo)
    result = converter.convert(session, limit=500)
    assert result == 1

    # There should be 2 records in the new table
    activity_cls = db.metadata._activity_cls
    assert activity_cls.query.count() == 2

    # Test snapshot model attributes after conversion
    todo = db.SpecialTodo.query.get(42)
    assert len(todo.versions()) == 2
    assert todo.version == 1
    insert_snapshot = todo.versions()[0]
    current_snapshot = todo.versions()[-1]

    assert insert_snapshot.version == 0
    assert insert_snapshot.title == "Spcial td #1"
    assert insert_snapshot.text == "Typo in title"
    assert insert_snapshot.chrononaut_meta["changed"] == todo.created_at
    assert current_snapshot.chrononaut_meta["changed"] > todo.created_at

    assert insert_snapshot.chrononaut_meta["changed"] == parse("2016-06-11 21:37:01.123456-01")
    assert current_snapshot.chrononaut_meta["changed"] == parse("2016-06-11 21:42:42.123457-01")

    assert current_snapshot.title == todo.title
    assert current_snapshot.text == todo.text

    # Test tracking after conversion
    time_0 = datetime.now(UTC)
    todo.title = "New title #1"
    db.session.commit()

    assert todo.diff(time_0)["title"] == ("Special Todo #1", "New title #1")


def test_convert_model_no_inheritance(db, session):
    sql = text(open("tests/files/seed_v0.1_db.sql", "r").read())
    session.execute(sql)
    session.commit()

    converter = HistoryModelDataConverter(db.Todo)
    result = converter.convert(session, limit=500)
    assert result == 3

    activity_cls = db.metadata._activity_cls
    assert activity_cls.query.count() == 6

    todo_1 = db.Todo.query.get(1)
    assert len(todo_1.versions()) == 3
    assert todo_1.version == 2

    insert_snapshot = todo_1.versions()[0]
    assert insert_snapshot.chrononaut_meta["changed"] == todo_1.created_at
    for i in range(1, len(todo_1.versions())):
        prev_version = todo_1.versions()[i - 1]
        next_version = todo_1.versions()[i]
        assert prev_version.chrononaut_meta["changed"] < next_version.chrononaut_meta["changed"]

    # Test change info moved to proper snapshot version
    prior_todo = todo_1.previous_version()
    assert "rationale" not in prior_todo.chrononaut_meta["extra_info"]
    current_snapshot = todo_1.versions()[-1]
    assert current_snapshot.version == 2
    # Test extra info migration
    assert (
        current_snapshot.chrononaut_meta["extra_info"]["rationale"]
        == "Should have always been complex"
    )

    # Test user info migration
    assert prior_todo.chrononaut_meta["user_info"]["user_id"] == 42
    assert prior_todo._key == {"id": 1}
    assert insert_snapshot.text == "Tpo in text"
    assert "user_id" not in insert_snapshot.chrononaut_meta["user_info"]

    # Test timestamp updates
    assert insert_snapshot.chrononaut_meta["changed"] == parse("2016-06-20 20:12:11.134125-01")
    assert current_snapshot.chrononaut_meta["changed"] == parse("2016-06-22 22:55:00.134125-01")

    # Polymorphic class not migrated directly won't see its history
    todo_2 = db.Todo.query.get(42)
    assert len(todo_2.versions()) == 0
    assert todo_2.version == 1


def test_convert_model_chunked(db, session):
    sql = text(open("tests/files/seed_v0.1_db.sql", "r").read())
    session.execute(sql)
    session.commit()

    converter = HistoryModelDataConverter(db.Todo)

    result = converter.convert(session, limit=2)
    assert result == 2

    result = converter.convert(session, limit=2)
    assert result == 1

    result = converter.convert(session, limit=2)
    assert result == 0

    result = converter.convert(session, limit=2)
    assert result == 0
