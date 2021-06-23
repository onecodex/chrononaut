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
	created_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id, version)
);

DROP TABLE IF EXISTS special_todo_history;
CREATE TABLE special_todo_history(
    id INTEGER NOT NULL,
	version INTEGER,
	changed TIMESTAMP WITH TIME ZONE,
    change_info JSONB,
	special_description TEXT,
	PRIMARY KEY (id, version)
);

INSERT INTO todos_history (id, title, text, todo_type, change_info, changed, version)
VALUES
    (1, 'Todo #1', 'Tpo in text', 'basic', '{"user_id": 42, "remote_addr": null}'::jsonb, '2016-06-22 20:44:52.134125-01', 0),
    (1, 'Todo #1', 'Text without typo', 'complex_todo', '{"user_id": 42, "remote_addr": null, "extra": {"rationale": "Should have always been complex"}}'::jsonb, '2016-06-22 22:55:00.134125-01', 1),
    (2, 'Todo #2', 'Todo text', 'basic', '{"user_id": null, "remote_addr": null}'::jsonb, '2016-06-22 20:11:52.134125-01', 0),
	(42, 'Spcial td #1', 'Typo in title', 'special', '{"user_id": null, "remote_addr": null}'::jsonb, '2016-06-11 21:42:42.123457-01', 0);

INSERT INTO special_todo_history (id, special_description, change_info, changed, version)
VALUES
	(42, 'Special description', '{"user_id": null, "remote_addr": null}'::jsonb, '2016-06-11 21:42:42.123457-01', 0);

INSERT INTO todos (id, title, text, todo_type, priority, version, created_at)
VALUES
    (1, 'Todo #1', 'Current todo text', 'basic', 'mid', 2, '2016-06-20 20:12:11.134125-01'),
	(42, 'Special Todo #1', 'Special todo text', 'special', 'high', 1, '2016-06-11 21:37:01.123456-01');

INSERT INTO special_todo (id, special_description)
VALUES
    (42, 'Special description #1');
