from chrononaut import record_changes


def test_record_changes(db, session):
    todo = db.Todo('Task 0', 'Testing...')
    session.add(todo)
    session.commit()

    with record_changes(todo, reason="Because it's done!"):
        todo.title = 'Task -1'

    session.commit()
    assert todo.versions()[-1].change_info['extra']['reason'] == "Because it's done!"
