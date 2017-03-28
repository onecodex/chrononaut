from datetime import datetime
import os

import flask
import flask_sqlalchemy
import sqlalchemy

import chrononaut

import pytest


@pytest.yield_fixture(scope='session')
def app(request):
    app = flask.Flask(__name__)
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'SQLALCHEMY_DATABASE_URI',
        'postgres://postgres@localhost/chrononaut_test'
    )
    ctx = app.app_context()
    ctx.push()

    yield app

    ctx.pop()


@pytest.yield_fixture(scope='session')
def unversioned_db(app, request):
    """An unversioned db fixture.
    """
    db = flask_sqlalchemy.SQLAlchemy(app)
    yield db


@pytest.yield_fixture(scope='session')
def db(app, request):
    """A versioned db fixture.
    """
    db = chrononaut.VersionedSQLAlchemy(app)
    models = generate_test_models(db)
    for model in models:
        setattr(db, model.__name__, model)
    db.create_all()
    yield db
    db.drop_all()


def generate_test_models(db):
    # A few classes for testing versioning
    class UnversionedTodo(db.Model):
        __tablename__ = 'unversioned_todos'
        id = db.Column('id', db.Integer, primary_key=True)
        title = db.Column(db.String(60))
        text = db.Column(db.String)
        done = db.Column(db.Boolean)
        pub_date = db.Column(db.DateTime)

        def __init__(self, title, text):
            self.title = title
            self.text = text
            self.done = False
            self.pub_date = datetime.utcnow()

    class Todo(db.Model, chrononaut.Versioned):
        __tablename__ = 'todos'
        __version_omit__ = ['done']
        id = db.Column('id', db.Integer, primary_key=True)  # FIXME: `todo_id` fails as a column name
        title = db.Column(db.String(60))
        text = db.Column(db.String)
        done = db.Column(db.Boolean)
        pub_date = db.Column(db.DateTime)

        def __init__(self, title, text):
            self.title = title
            self.text = text
            self.done = False
            self.pub_date = datetime.utcnow()

    return Todo, UnversionedTodo


@pytest.yield_fixture(scope='function')
def session(db, request):
    """Creates a new database session for a test."""
    connection = db.engine.connect()
    transaction = connection.begin()

    options = dict(bind=connection, binds={})
    session = db.create_scoped_session(options=options)
    session.begin_nested()

    # session is actually a scoped_session
    # for the `after_transaction_end` event, we need a session instance to
    # listen for, hence the `session()` call
    @sqlalchemy.event.listens_for(session(), 'after_transaction_end')
    def restart_savepoint(sess, trans):
        if trans.nested and not trans._parent.nested:
            session.expire_all()
            session.begin_nested()

    db.session = session

    yield session

    transaction.rollback()
    connection.close()
    session.remove()
