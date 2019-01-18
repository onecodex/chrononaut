
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

from flask_sqlalchemy import SignallingSession, SQLAlchemy


# Chrononaut imports
from chrononaut.change_info import append_recorded_changes, RecordChanges, increment_version_on_insert
from chrononaut.context_managers import append_change_info, extra_change_info, rationale
from chrononaut.exceptions import ChrononautException
from chrononaut.flask_versioning import create_version
from chrononaut.versioned import Versioned


def versioned_objects(items):
    for obj in items:
        if hasattr(obj, '__history_mapper__'):
            yield obj


def versioned_session(session):
    @event.listens_for(session, 'before_flush')
    def before_flush(session, flush_context, instances):
        """A listener that handles state changes for objects with Chrononaut mixins.
        """
        for obj in session.new:
            if hasattr(obj, '__chrononaut_record_change_info__'):
                append_recorded_changes(obj, session)
            if hasattr(obj, '__chrononaut_primary_key_nonunique__'):
                increment_version_on_insert(obj)

        for obj in session.dirty:
            if hasattr(obj, '__history_mapper__'):
                create_version(obj, session)
            if hasattr(obj, '__chrononaut_record_change_info__'):
                append_recorded_changes(obj, session)

        for obj in session.deleted:
            if hasattr(obj, '__history_mapper__'):
                create_version(obj, session, deleted=True)


class VersionedSignallingSession(SignallingSession):
    """A subclass of Flask-SQLAlchemy's SignallingSession that supports
    versioned and change info session information.
    """
    pass


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
    :class:`Versioned` mixin.
    """
    def create_session(self, options):
        return sqlalchemy.orm.sessionmaker(class_=VersionedSignallingSession, db=self, **options)


__all__ = ['VersionedSQLAlchemy', 'Versioned', 'RecordChanges',
           'append_change_info', 'extra_change_info', 'rationale', 'ChrononautException']
