DROP TABLE IF EXISTS todos_history;
CREATE TABLE todos_history(
    id INTEGER NOT NULL,
	title VARCHAR(60),
	text TEXT,
	todo_type VARCHAR(16),
	done BOOLEAN,
	starred BOOLEAN,
	pub_date TIMESTAMP WITH TIME ZONE,
	version INTEGER,
    changed TIMESTAMP WITH TIME ZONE,
    change_info JSONB,
	PRIMARY KEY (id, version)
);

INSERT INTO todos_history (id, title, text, todo_type, change_info, changed, version)
VALUES
    (1, 'Todo #1', 'Tpo in text', 'simple_todo', '{"user_id": 42, "remote_addr": null}'::jsonb, '2016-06-22 20:44:52.134125-01', 0),
    (1, 'Todo #1', 'Text without typo', 'complex_todo', '{"user_id": 42, "remote_addr": null, "extra": {"rationale": "Should have always been complex"}}'::jsonb, '2016-06-22 22:55:00.134125-01', 1),
    (2, 'Todo #2', 'Todo text', 'simple_todo', '{"user_id": null, "remote_addr": null}'::jsonb, '2016-06-22 20:11:52.134125-01', 0);
