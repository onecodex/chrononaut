"""
Main Chrononaut exports: Versioned model mixin, VersionSQLAlchemy db factor, and extra_change_info
context manager.
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
    """A context manager for appending extra change_info to Chrononaut versioned tables.
    """
    if _app_ctx_stack.top is None:
        raise ChrononautException('Can only use `extra_change_info` in a Flask app context.')
    setattr(g, '__version_extra_change_info__', kwargs)
    yield
    delattr(g, '__version_extra_change_info__')


class Versioned(object):
    """
    Can use __version_untracked__ to prevent fields from triggering an update

    Can also use __version_hidden__ to trigger an update (and be captured in the `change_info`
        column) but not to save the column values
    """
    @declared_attr
    def __mapper_cls__(cls):
        def map(cls, *arg, **kw):
            mp = mapper(cls, *arg, **kw)
            history_mapper(mp)
            return mp
        return map

    def versions(self, raw_query=False):
        # get the primary keys for this table
        prim_keys = [k.key for k in self.__history_mapper__.primary_key if k.key != 'version']

        # find all previous versions that have the same primary keys as myself
        query = self.__history_mapper__.class_.query.filter_by(
            **{k: getattr(self, k) for k in prim_keys}
        )

        if raw_query:
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
            'user_email': self._fetch_current_user_email(),
            'ip': self._fetch_remote_addr(),
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
    """A subclass of `SQLAlchemy` that uses `VersionedSignallingSession` and supports a
       `require_extra_change_info` strict change-tracking mode.
    """
    def create_session(self, options):
        return sqlalchemy.orm.sessionmaker(class_=VersionedSignallingSession, db=self, **options)


__all__ = ['VersionedSQLAlchemy', 'Versioned', 'extra_change_info', 'ChrononautException']
