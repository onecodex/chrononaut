from datetime import datetime
import os

import flask
import flask_security
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
    app.config['SECRET_KEY'] = '+BU9wMx=xvD\YV'
    app.config['LOGIN_DISABLED'] = False
    app.config['WTF_CSRF_ENABLED'] = False
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


@pytest.yield_fixture(scope='function')
def strict_session(app, request):
    app.config['CHRONONAUT_REQUIRE_EXTRA_CHANGE_INFO'] = True
    yield
    app.config['CHRONONAUT_REQUIRE_EXTRA_CHANGE_INFO'] = False


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
        __chrononaut_hidden__ = ['done']
        __chrononaut_untracked__ = ['starred']
        id = db.Column('id', db.Integer, primary_key=True)  # FIXME: `todo_id` fails as a col name
        title = db.Column(db.String(60))
        text = db.Column(db.Text)
        done = db.Column(db.Boolean)
        starred = db.Column(db.Boolean)
        pub_date = db.Column(db.DateTime)

        def __init__(self, title, text):
            self.title = title
            self.text = text
            self.done = False
            self.starred = False
            self.pub_date = datetime.utcnow()

    class Report(db.Model, chrononaut.Versioned):
        __tablename__ = 'report'
        __chrononaut_tablename__ = 'rep_history'
        report_id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String(60))
        text = db.Column(db.Text)

    roles_users = db.Table('roles_users',
                           db.Column('user_id', db.Integer(), db.ForeignKey('appuser.id')),
                           db.Column('role_id', db.Integer(), db.ForeignKey('role.id')))

    class User(db.Model, flask_security.UserMixin):
        __tablename__ = 'appuser'
        id = db.Column(db.Integer, primary_key=True)
        email = db.Column(db.String(255), unique=True)
        password = db.Column(db.String(255))
        active = db.Column(db.Boolean())
        confirmed_at = db.Column(db.DateTime())
        roles = db.relationship('Role', secondary=roles_users,
                                backref=db.backref('users', lazy='dynamic'))

    class Role(db.Model, flask_security.UserMixin):
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(80), unique=True)
        description = db.Column(db.String(255))

    return Todo, UnversionedTodo, Report, User, Role


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


@pytest.fixture()
def security_app(app, db):
    sqlalchemy_datastore = flask_security.SQLAlchemyUserDatastore(db, db.User, db.Role)

    def create():
        app.security = flask_security.Security(app, datastore=sqlalchemy_datastore)
        return app

    return create


@pytest.fixture(scope='function')
def app_client(security_app, session, db):
    app = security_app()
    user = app.security.datastore.create_user(email='test@example.com', password='password',
                                              active=True)
    session.add(user)
    session.commit()
    client = app.test_client(use_cookies=True)
    return client


@pytest.yield_fixture(scope='function')
def logged_in_user(session, db, app_client):
    user = db.User.query.first()
    with app_client:
        # Note we have no routes, so 404s if follow_redirects=True
        response = app_client.post('/login', data={
                                   "email": user.email,
                                   "password": 'password'})
        assert response.status_code == 302
        assert flask_security.current_user == user
        yield user
