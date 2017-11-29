
# -*- coding: utf-8 -*-
"""
    chrononaut
    ~~~~~~~~~~~~~~~~~~~
    A history mixin for audit logging, record locking, and time travel with Flask-SQLAlchemy
    :copyright: (c) 2017 by Reference Genomics, Inc.
    :license: MIT, see LICENSE for more details.
"""

import sqlalchemy
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import mapper, object_mapper
from sqlalchemy.orm.exc import UnmappedColumnError

from sqlalchemy import event


from flask_sqlalchemy import SignallingSession, SQLAlchemy

# For our specific change_info logging
from flask import request
from flask.globals import _app_ctx_stack, _request_ctx_stack

# Chrononaut imports
from chrononaut.exceptions import ChrononautException
from chrononaut.context_managers import append_change_info, extra_change_info
from chrononaut.history_mapper import history_mapper
from chrononaut.flask_versioning import create_version


def _in_flask_context():
    if _app_ctx_stack.top is None or _request_ctx_stack.top is None:
        return False
    else:
        return True


class Versioned(object):
    """A mixin for use with Flask-SQLAlchemy declarative models. To get started, simply add
    the :class:`Versioned` mixin to one of your models::

        class User(db.Model, Versioned):
            __tablename__ = 'appuser'
            id = db.Column(db.Integer, primary_key=True)
            email = db.Column(db.String(255))
            ...

    The above will then automatically track updates to the ``User`` model and create an
    ``appuser_history`` table for tracking prior versions of each record. By default,
    *all* columns are tracked. By default, change information includes a ``user_id``
    and ``remote_addr``, which are set to automatically populate from Flask-Login's
    ``current_user`` in the :meth:`_capture_change_info` method. Subclass :class:`Versioned`
    and override a combination of :meth:`_capture_change_info`, :meth:`_fetch_current_user_id`,
    and :meth:`_get_custom_change_info`. This ``change_info`` is stored in a JSON column in your
    application's database and has the following rough layout::

        {
            "user_id": "A unique user ID (string) or None",
            "remote_addr": "The user IP (string) or None",
            "extra": {
                ...  # Optional extra fields
            },
            "hidden_cols_changed": [
                ...  # A list of any hidden fields changed in the version
            ]
        }


    Note that the latter two keys will not exist if they would otherwise be empty. You may
    provide a list of column names that you do not want to track using the optional
    ``__chrononaut_untracked__`` field or you may provide a list of columns you'd like to
    "hide" (i.e., track updates to the columns but not their values) using the
    ``__chrononaut_hidden__`` field. This can be useful for sensitive values, e.g., passwords,
    which you do not want to retain indefinitely.
    """
    @declared_attr
    def __mapper_cls__(cls):
        def map_function(cls, *arg, **kw):
            mp = mapper(cls, *arg, **kw)
            history_mapper(mp)
            return mp
        return map_function

    def versions(self, before=None, after=None, return_query=False):
        """Fetch the history of the given object from its history table.

        :param before: Return changes only _before_ the provided ``DateTime``.
        :param before: Return changes only _after_ the provided ``DateTime``.
        :param return_query: Return a SQLAlchemy query instead of a list of models.
        :return: List of history models for the given object (or a query object).
        """
        # get the primary keys for this table
        prim_keys = [k.key for k in self.__history_mapper__.primary_key if k.key != 'version']

        # Find all previous versions that have the same primary keys as myself
        query = self.__history_mapper__.class_.query.filter_by(
            **{k: getattr(self, k) for k in prim_keys}
        )

        # Filter additionally by date as needed
        if before is not None:
            query = query.filter(self.__history_mapper__.class_.changed <= before)
        if after is not None:
            query = query.filter(self.__history_mapper__.class_.changed >= after)

        # Order by the version
        query = query.order_by(self.__history_mapper__.class_.version)

        if return_query:
            return query
        else:
            return query.all()

    def version_at(self, at):
        """Fetch the history model at a specific time (or None)

        :param at: The DateTime at which to find the history record.
        :return: A history model at the given point in time or the model itself if that is current.
        """
        query = self.versions(after=at, return_query=True)
        history_model = query.first()
        if history_model is None:
            return self
        else:
            return history_model

    def has_changed_since(self, since):
        """Check if there are any changes since a given time.

        :param since: The DateTime from which to find any history records
        :return: ``True`` if there have been any changes. ``False`` if not.
        """
        return self.version_at(at=since) is not self

    def diff(self, from_model, to=None, include_hidden=False):
        """Enumerate the changes from a prior history model to a later history model or the current model's
        state (if ``to`` is ``None``).

        :param from_model: A history model to diff from.
        :param to: A history model or ``None``.
        :return: A dict of column names and ``(from, to)`` value tuples
        """
        to_model = to or self
        untracked_cols = set(getattr(self, '__chrononaut_untracked__', []))

        for k in self.__history_mapper__.primary_key:
            if k.key == 'version':
                continue
            if getattr(from_model, k.key) != getattr(to_model, k.key):
                raise ChrononautException('You can only diff models with the same primary keys.')

        if not isinstance(from_model, self.__history_mapper__.class_):
            raise ChrononautException('Cannot diff from a non-history model.')

        if to_model is not self and from_model.changed > to_model.changed:
            raise ChrononautException('Diffs must be chronological. Your from_model '
                                      'post-dates your to.')

        # TODO: Refactor this and `create_version` so some of the object mapper
        #       iteration is not duplicated twice
        diff = {}
        obj_mapper = object_mapper(from_model)
        for om in obj_mapper.iterate_to_root():
            for obj_col in om.local_table.c:
                if 'version_meta' in obj_col.info or obj_col.key in untracked_cols:
                    continue
                try:
                    prop = obj_mapper.get_property_by_column(obj_col)
                except UnmappedColumnError:
                    continue

                # First check the history model's columns
                from_val = getattr(from_model, prop.key)
                to_val = getattr(to_model, prop.key)
                if from_val != to_val:
                    diff[prop.key] = (from_val, to_val)

        # If `include_hidden` we need to enumerate through every
        # model *since* the from_model and see if `change_info` includes
        # hidden columns. We only need to do this for non-history instances.
        if include_hidden and isinstance(to_model, self.__class__):
            from_versions = self.versions(after=from_model.changed)
            for from_version in from_versions:
                if 'hidden_cols_changed' in from_version.change_info:
                    for hidden_col in from_version.change_info['hidden_cols_changed']:
                        diff[hidden_col] = (None, getattr(to_model, hidden_col))
                    break

        return diff

    def _capture_change_info(self):
        """Capture the change info for the new version. By default calls:

        (1) :meth:`_fetch_current_user_id` which should return a string or None; and
        (2) :meth:`_fetch_remote_addr` which should return an IP address string or None;
        (3) :meth:`_get_custom_change_info` which should return a 1-depth dict of additional keys.

        These 3 methods generate a ``change_info`` and with 2+ top-level keys (``user_id``,
        ``remote_addr``, and any keys from :meth:`_get_custom_change_info`)
        """
        change_info = {
            'user_id': self._fetch_current_user_id(),
            'remote_addr': self._fetch_remote_addr(),
        }
        extra_info = self._get_custom_change_info()
        if extra_info:
            change_info.update(extra_info)
        return change_info

    def _fetch_current_user_id(self):
        """Return the current user ID.

        :return: A unique user ID string or ``None`` if not available.
        """
        if not _in_flask_context():
            return None
        try:
            from flask_login import current_user
            return current_user.email if current_user.is_authenticated else None
        except ImportError:
            return None

    def _fetch_remote_addr(self):
        """Return the IP address for the current user.

        :return: An IP address string or ``None`` if not available.
        """
        if not _in_flask_context():
            return None
        return request.remote_addr

    def _get_custom_change_info(self):
        """Optionally return additional ``change_info`` fields to be
        inserted into the history record. By default, this checks for a Flask app
        config variable `CHRONONAUT_EXTRA_CHANGE_INFO_FUNC` and calls the callable
        stored there (note that this may need to be wrapped with `staticfunction`).
        If not defined, returns no additional change info. Note that :class:`Versioned`
        may be subclassed to further refine how custom change info is generated and propagated.

        :return: A dictionary of additional ``change_info`` keys and values
        """
        extra_info = self._sa_instance_state.session.app.config.get('CHRONONAUT_EXTRA_CHANGE_INFO_FUNC')
        if extra_info:
            return extra_info()
        return None


def versioned_objects(items):
    for obj in items:
        if hasattr(obj, '__history_mapper__'):
            yield obj


def versioned_session(session):
    @event.listens_for(session, 'before_flush')
    def before_flush(session, flush_context, instances):
        for obj in versioned_objects(session.dirty):
            create_version(obj, session)
        for obj in versioned_objects(session.deleted):
            create_version(obj, session, deleted=True)


class VersionedSignallingSession(SignallingSession):
    """A subclass of Flask-SQLAlchemy's SignallingSession that supports
    versioned session information.
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


__all__ = ['VersionedSQLAlchemy', 'Versioned', 'append_change_info', 'extra_change_info',
           'ChrononautException']
