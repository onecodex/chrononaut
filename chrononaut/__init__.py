# -*- coding: utf-8 -*-
"""
    chrononaut
    ~~~~~~~~~~~~~~~~~~~
    A history mixin for audit logging, record locking, and time travel with Flask-SQLAlchemy
    :copyright: (c) 2017 by Reference Genomics, Inc.
    :license: MIT, see LICENSE for more details.
"""

import sqlalchemy
from sqlalchemy import event
from flask import g
from flask_sqlalchemy import SignallingSession, SQLAlchemy


# Chrononaut imports
from chrononaut.change_info import (
    append_recorded_changes,
    RecordChanges,
    increment_version_on_insert,
)
from chrononaut.context_managers import append_change_info, extra_change_info, rationale
from chrononaut.exceptions import ChrononautException
from chrononaut.flask_versioning import create_version
from chrononaut.flask_versioning import is_modified
from chrononaut.versioned import Versioned
from chrononaut.models import HistorySnapshot, activity_factory


def versioned_objects(items):
    for obj in items:
        if hasattr(obj, "__versioned__"):
            yield obj


def versioned_session(session):
    @event.listens_for(session, "before_flush")
    def before_flush(session, flush_context, instances):
        """A listener that handles state changes for objects with Chrononaut mixins."""
        for obj in session.new:
            if hasattr(obj, "__chrononaut_record_change_info__"):
                append_recorded_changes(obj, session)
            if hasattr(obj, "__chrononaut_primary_key_nonunique__"):
                increment_version_on_insert(obj)

        for obj in session.dirty:
            if hasattr(obj, "__versioned__") and is_modified(obj):
                # Objects cannot be updated in the `after_flush` step hence bumping the version here
                obj.version = obj.version + 1 if obj.version is not None else 1
            if hasattr(obj, "__chrononaut_record_change_info__"):
                append_recorded_changes(obj, session)

        for obj in session.deleted:
            if hasattr(obj, "__chrononaut_version__") and not hasattr(
                g, "__allow_deleting_history__"
            ):
                raise ChrononautException("Cannot commit version removal")
            elif hasattr(obj, "__versioned__"):
                obj.version = obj.version + 1 if obj.version is not None else 1
                create_version(obj, session, deleted=True)

    @event.listens_for(session, "after_flush")
    def after_flush(session, flush_context):
        # Tracking inserts in `after_flush` because we need the id to be set
        for obj in session.new:
            if hasattr(obj, "__versioned__"):
                create_version(obj, session, created=True)
        # Tracking updates in `after_flush` due to foreign keys being only set during flush
        for obj in session.dirty:
            if hasattr(obj, "__versioned__"):
                create_version(obj, session)


class VersionedSignallingSession(SignallingSession):
    """A subclass of Flask-SQLAlchemy's SignallingSession that supports
    versioned and change info session information.
    """

    def delete(self, instance):
        if isinstance(instance, HistorySnapshot):
            if not hasattr(g, "__allow_deleting_history__"):
                raise ChrononautException("Cannot remove version info")
            super().delete(instance._activity_obj)
        else:
            super().delete(instance)


versioned_session(VersionedSignallingSession)


class VersionedSQLAlchemy(SQLAlchemy):
    """A subclass of the :class:`SQLAlchemy` used to control a SQLAlchemy integration
    to a Flask application.

    Two usage modes are supported (as in Flask-SQLAlchemy). One is directly binding to a
    Flask application::

        app = Flask(__name__)
        db = VersionedSQLAlchemy(app)

    The other is by creating the ``db`` object and then later initializing it for the application::


        db = VersionedSQLAlchemy()

        # Later/elsewhere
        def configure_app():
            app = Flask(__name__)
            db.init_app(app)
            return app


    At its core, the :class:`VersionedSQLAlchemy` class simply ensures that database ``session``
    objects properly listen to events and create version records for models with the
    :class:`Versioned` mixin. It also introduces the `chrononaut_activity` table which holds
    the data snapshots of the edited entries.
    It can be accessed via `metadata._activity_cls`.
    """

    def __init__(self, *args, **kwargs):
        super(VersionedSQLAlchemy, self).__init__(*args, **kwargs)
        self.metadata._activity_cls = activity_factory(self.Model)

    def create_session(self, options):
        return sqlalchemy.orm.sessionmaker(class_=VersionedSignallingSession, db=self, **options)


__all__ = [
    "VersionedSQLAlchemy",
    "Versioned",
    "RecordChanges",
    "append_change_info",
    "extra_change_info",
    "rationale",
    "ChrononautException",
]
