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


def test_change_info(db, session, logged_in_user):
    """Test that change info is as expected with a user
    """
    todo = db.Todo('First Todo', 'Check change info')
    session.add(todo)
    session.commit()
    todo.title = 'Modified'
    session.commit()

    prior_todo = todo.versions()[0]
    assert prior_todo.change_info['user_id'] == 'test@example.com'
    assert prior_todo.change_info['ip_address'] == '127.0.0.1'
