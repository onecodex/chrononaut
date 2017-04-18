
# -*- coding: utf-8 -*-
"""
    chrononaut
    ~~~~~~~~~~~~~~~~~~~
    A history mixin with audit logging, record locking, and time travel for SQLAlchemy
    :copyright: (c) 2017 by Reference Genomics, Inc.
    :license: MIT, see LICENSE for more details.
"""
from contextlib import contextmanager

import sqlalchemy
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import mapper

from sqlalchemy import event


from flask_sqlalchemy import SignallingSession, SQLAlchemy

# For our specific change_info logging
from flask import g, request
from flask.globals import _app_ctx_stack, _request_ctx_stack

# Chrononaut imports
from chrononaut.exceptions import ChrononautException
from chrononaut.history_mapper import history_mapper
from chrononaut.flask_versioning import create_version


@contextmanager
def extra_change_info(**kwargs):
    """A context manager for appending extra change_info to Chrononaut
    :class:`Versioned` tables.
    """
    if _app_ctx_stack.top is None:
        raise ChrononautException('Can only use `extra_change_info` in a Flask app context.')
    setattr(g, '__version_extra_change_info__', kwargs)
    yield
    delattr(g, '__version_extra_change_info__')


class Versioned(object):
    """The Versioned mixin should be mixed into a FlaskSQLAlchemy model and used
    with a VersionedSQLAlchemy database object. This will generate an additional
    history table in your database and set up automated update tracking for the given
    model.

    If you want to mark a column as "untracked" (i.e., do not create a history record),
    add a `__chrononaut_untracked__` field to your model with a list of column names. If you
    want to hide specific column values, but track the changes, use `__chrononaut_hidden__`.
    The latter will capture which columns were modified in a `hidden_cols_changed` field
    within the `change_info` JSON column on the generated history table.
    """
    @declared_attr
    def __mapper_cls__(cls):
        def map(cls, *arg, **kw):
            mp = mapper(cls, *arg, **kw)
            history_mapper(mp)
            return mp
        return map

    def versions(self, return_query=False):
        """Fetch the history of the given object from its history table.

        :param return_query: Return a SQLAlchemy query instead of a list of models.
        :return: List of history models for the given object (or a query object).
        """
        # get the primary keys for this table
        prim_keys = [k.key for k in self.__history_mapper__.primary_key if k.key != 'version']

        # find all previous versions that have the same primary keys as myself
        query = self.__history_mapper__.class_.query.filter_by(
            **{k: getattr(self, k) for k in prim_keys}
        )

        if return_query:
            return query
        else:
            return query.all()

    def _capture_change_info(self):
        """
        Capture the change info for the new version. By default calls:
        (1) _fetch_current_user_email() which should return a string or None; and
        (2) _fetch_remote_addr() which should return an IP address string or None;
        (3) _get_custom_change_info() which should return a 1-depth dict of additional keys.
        """
        change_info = {
            'user_id': self._fetch_current_user_email(),
            'ip_address': self._fetch_remote_addr(),
        }
        extra_info = self._get_custom_change_info()
        if extra_info:
            change_info.update(extra_info)
        return change_info

    @staticmethod
    def _in_flask_context():
        if _app_ctx_stack.top is None or _request_ctx_stack.top is None:
            return False
        else:
            return True

    def _fetch_current_user_email(self):
        if not self._in_flask_context():
            return None
        try:
            from flask_login import current_user
            return current_user.email if current_user.is_authenticated else None
        except AttributeError:
            return None

    def _fetch_remote_addr(self):
        if not self._in_flask_context():
            return None
        return request.remote_addr

    def _get_custom_change_info(self):
        pass


def versioned_objects(iter):
    for obj in iter:
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
    """A subclass of `SQLAlchemy` that uses `VersionedSignallingSession`.
    """
    def create_session(self, options):
        return sqlalchemy.orm.sessionmaker(class_=VersionedSignallingSession, db=self, **options)


__all__ = ['VersionedSQLAlchemy', 'Versioned', 'extra_change_info', 'ChrononautException']
