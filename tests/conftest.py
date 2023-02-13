from chrononaut.flask_versioning import serialize_datetime, UTC
from datetime import datetime
import os
from enum import Enum

import flask
from flask import g, _request_ctx_stack
import flask_security
import flask_sqlalchemy
import sqlalchemy
import random
import string

import chrononaut

import pytest


@pytest.fixture(scope="session")
def app(request):
    app = flask.Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "SQLALCHEMY_DATABASE_URI", "postgresql://postgres@localhost/chrononaut_test"
    )
    app.config["SECRET_KEY"] = "+BU9wMx=xvD\\YV"
    app.config["LOGIN_DISABLED"] = False
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECURITY_PASSWORD_SALT"] = "".join(
        random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits)
        for _ in range(8)
    )
    with app.app_context():
        yield app


@pytest.fixture(scope="session")
def unversioned_db(app, request):
    """An unversioned db fixture."""
    db = flask_sqlalchemy.SQLAlchemy(app)
    yield db


@pytest.fixture(scope="session")
def db(app, request):
    """A versioned db fixture."""
    db = chrononaut.VersionedSQLAlchemy(app)
    models = generate_test_models(db)
    for model in models:
        setattr(db, model.__name__, model)
    db.create_all()
    try:
        yield db
    finally:
        db.drop_all()


@pytest.fixture(scope="function")
def strict_session(app, request):
    app.config["CHRONONAUT_REQUIRE_EXTRA_CHANGE_INFO"] = True
    try:
        yield
    finally:
        app.config["CHRONONAUT_REQUIRE_EXTRA_CHANGE_INFO"] = False


@pytest.fixture(scope="function")
def extra_change_info(app, request):
    app.config["CHRONONAUT_EXTRA_CHANGE_INFO_FUNC"] = lambda: {"extra_field": True}
    try:
        yield
    finally:
        app.config["CHRONONAUT_EXTRA_CHANGE_INFO_FUNC"] = None


def generate_test_models(db):
    # A few classes for testing versioning
    class UnversionedTodo(db.Model):
        __tablename__ = "unversioned_todos"
        id = db.Column("id", db.Integer, primary_key=True)
        title = db.Column(db.String(60))
        text = db.Column(db.String)
        done = db.Column(db.Boolean)
        pub_date = db.Column(db.DateTime)

        def __init__(self, title, text):
            self.title = title
            self.text = text
            self.done = False
            self.pub_date = datetime.now(UTC)

    class Priority(Enum):
        LOW = "low"
        MEDIUM = "mid"
        HIGH = "high"

    class Todo(db.Model, chrononaut.Versioned):
        __tablename__ = "todos"
        __chrononaut_hidden__ = ["done"]
        __chrononaut_untracked__ = ["starred"]
        __chrononaut_disable_indices__ = ["pub_date"]
        id = db.Column("id", db.Integer, primary_key=True)  # FIXME: `todo_id` fails as a col name
        title = db.Column(db.String(60))
        text = db.Column(db.Text)
        todo_type = db.Column(db.String(16))
        done = db.Column(db.Boolean)
        starred = db.Column(db.Boolean)
        pub_date = db.Column(db.DateTime(timezone=True), index=True)
        priority = db.Column(
            db.Enum(
                Priority,
                validate_strings=True,
                native_enum=False,
                create_constraint=False,
                values_callable=lambda x: [e.value for e in x],
            ),
            nullable=False,
            default=Priority.MEDIUM,
        )
        created_at = db.Column(db.DateTime(timezone=True), default=sqlalchemy.func.now())

        __mapper_args__ = {"polymorphic_identity": "basic", "polymorphic_on": todo_type}

        def __init__(self, title, text, preset_id=None):
            self.title = title
            self.text = text
            self.done = False
            self.starred = False
            self.pub_date = datetime.now(UTC)
            if preset_id:
                self.id = preset_id

        @sqlalchemy.orm.validates("todo_type")
        def validate_todo_type(self, k, v):
            if v == "invalid_type":
                raise Exception("todo_type could not be validated")
            else:
                return v

    class SpecialTodo(Todo, chrononaut.Versioned):
        # Joined table inheritance example
        __tablename__ = "special_todo"
        __mapper_args__ = {"polymorphic_identity": "special"}
        id = db.Column(db.Integer, db.ForeignKey("todos.id"), primary_key=True)
        special_description = db.Column(db.Text)

    class BoringTodo(Todo, chrononaut.Versioned):
        # Single table inheritance -- no table of its own
        __mapper_args__ = {"polymorphic_identity": "boring"}

    class Report(db.Model, chrononaut.Versioned):
        __tablename__ = "report"
        __chrononaut_tablename__ = "rep_history"
        __chrononaut_copy_validators__ = True
        report_id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String(60), index=True)
        text = db.Column(db.Text)

        @sqlalchemy.orm.validates("title")
        def validate_title(self, k, v):
            if v == "invalid_title":
                raise Exception("title could not be validated")
            else:
                return v

    roles_users = db.Table(
        "roles_users",
        db.Column("user_id", db.Integer(), db.ForeignKey("appuser.id")),
        db.Column("role_id", db.Integer(), db.ForeignKey("role.id")),
    )

    class Role(db.Model, flask_security.RoleMixin, chrononaut.Versioned):
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(80), unique=True)
        description = db.Column(db.String(255))

    class User(db.Model, flask_security.UserMixin, chrononaut.Versioned):
        __tablename__ = "appuser"
        id = db.Column(db.Integer, primary_key=True)
        email = db.Column(db.String(255), unique=True)
        password = db.Column(db.String(255))
        active = db.Column(db.Boolean())
        confirmed_at = db.Column(db.DateTime(timezone=True))
        primary_role_id = db.Column(db.Integer, db.ForeignKey("role.id"))
        primary_role = db.relationship("Role")
        roles = db.relationship(
            "Role", secondary=roles_users, backref=db.backref("users", lazy="dynamic")
        )

    class ChangeLog(db.Model, chrononaut.RecordChanges, chrononaut.Versioned):
        id = db.Column(db.Integer, primary_key=True)
        note = db.Column(db.Text)

    return Todo, UnversionedTodo, SpecialTodo, Report, User, Role, ChangeLog, Priority


@pytest.fixture(scope="function", autouse=True)
def session(db):
    """Creates a new database session for a test."""
    connection = db.engine.connect()
    transaction = connection.begin()

    options = dict(bind=connection, binds={})
    session = db.create_scoped_session(options=options)
    session.begin_nested()

    # session is actually a scoped_session
    # for the `after_transaction_end` event, we need a session instance to
    # listen for, hence the `session()` call
    @sqlalchemy.event.listens_for(session(), "after_transaction_end")
    def restart_savepoint(sess, trans):
        if trans.nested and not trans._parent.nested:
            session.expire_all()
            session.begin_nested()

    db.session = session

    try:
        yield session
    finally:
        transaction.rollback()
        connection.close()
        session.remove()


@pytest.fixture(scope="session")
def security_app(app, db):
    sqlalchemy_datastore = flask_security.SQLAlchemyUserDatastore(db, db.User, db.Role)

    security = flask_security.Security(datastore=sqlalchemy_datastore)
    security.init_app(app)
    try:
        yield app
    finally:
        app.security = None
        app.blueprints.pop("security")


@pytest.fixture(scope="function")
def app_client(security_app):
    yield security_app.test_client(use_cookies=True)


@pytest.fixture(scope="function")
def user(db, session):
    user = db.User(email="test@example.com", password="password", active=True)
    role = db.Role(name="Admin")
    session.add(user)
    session.add(role)
    session.commit()
    yield user


@pytest.fixture(scope="function")
def anonymous_user(app_client):
    with app_client:
        app_client.post("/login")
        assert not hasattr(flask_security.current_user, "email")
        yield flask_security.current_user


@pytest.fixture(scope="function")
def logged_in_user(security_app, user):
    with security_app.test_request_context(environ_base={"REMOTE_ADDR": "10.0.0.1"}):
        original = security_app.login_manager._load_user
        if hasattr(g, "_login_user"):
            delattr(g, "_login_user")

        def _load_user_from_request():
            _request_ctx_stack.top.user = user
            g._login_user = user
            return user

        security_app.login_manager._load_user = _load_user_from_request
        try:
            yield user
        finally:
            security_app.login_manager._load_user = original
