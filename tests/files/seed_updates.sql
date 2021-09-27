UPDATE todos SET version = 4, text = 'Changed current text' WHERE id = 1;

INSERT INTO todos_history (id, title, text, todo_type, change_info, changed, version)
VALUES
    (1, 'Todo #1', 'Current todo text (should be same as one in todo table)', 'basic', '{"user_id": 11, "remote_addr": null}'::jsonb, '2016-06-23 11:12:00.134125-01', 2),
    (1, 'Todo #1', 'Current todo text #2', 'basic', '{"user_id": 13, "remote_addr": null}'::jsonb, '2016-06-23 11:42:00.134125-01', 3);


INSERT INTO todos (id, title, text, todo_type, priority, version, created_at)
VALUES
    (10, 'Todo #10', 'Text', 'basic', 'mid', 0, '2016-06-28 20:40:00.134125-01'),
    (44, 'Todo #44', 'With text', 'basic', 'mid', 0, '2016-06-28 20:40:00.134125-01');
