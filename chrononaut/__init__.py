"""
Versioned mixin class and other utilities.


Partially derived from/see for reference:
http://docs.sqlalchemy.org/en/latest/orm/examples.html?highlight=version#module-examples.versioned_history
http://docs.sqlalchemy.org/en/latest/_modules/examples/versioned_history/test_versioning.html
http://docs.sqlalchemy.org/en/latest/_modules/examples/versioned_history/history_meta.html
"""
from contextlib import contextmanager

import sqlalchemy
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import mapper, attributes, object_mapper
from sqlalchemy.orm.exc import UnmappedColumnError
from sqlalchemy import event
from sqlalchemy.orm.properties import RelationshipProperty

from flask_sqlalchemy import SignallingSession, SQLAlchemy

# For our specific change_info logging
from flask import g, request
from flask.globals import _app_ctx_stack, _request_ctx_stack

# Chrononaut imports
from chrononaut.exceptions import ChrononautException
from chrononaut.history_mapper import history_mapper


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


def fetch_recorded_changes():
    if _app_ctx_stack.top is None:
        return None
    return getattr(g, '__version_extra_change_info__', None)


def create_version(obj, session, deleted=False):
    obj_mapper = object_mapper(obj)
    history_mapper = obj.__history_mapper__
    history_cls = history_mapper.class_

    obj_state = attributes.instance_state(obj)

    attr = {}

    hidden_cols = set(getattr(obj, '__version_hidden__', []))
    untracked_cols = set(getattr(obj, '__version_untracked__', []))

    changed_cols = set()

    for om, hm in zip(obj_mapper.iterate_to_root(), history_mapper.iterate_to_root()):
        if hm.single:
            continue

        for obj_col in om.local_table.c:
            if 'version_meta' in obj_col.info or obj_col.key in untracked_cols:
                continue

            # get the value of the attribute based on the MapperProperty related to the
            # mapped column.  this will allow usage of MapperProperties that have a
            # different keyname than that of the mapped column.
            try:
                prop = obj_mapper.get_property_by_column(obj_col)
            except UnmappedColumnError:
                # in the case of single table inheritance, there may be columns on the mapped
                # table intended for the subclass only. the "unmapped" status of the subclass
                # column on the base class is a feature of the declarative module.
                continue

            # expired object attributes and also deferred cols might not be in the dict.
            # force it to load no matter what by using getattr().
            if prop.key not in obj_state.dict:
                getattr(obj, prop.key)

            a, u, d = attributes.get_history(obj, prop.key)

            if d:
                attr[prop.key] = d[0]
                changed_cols.add(prop.key)
            elif u:
                attr[prop.key] = u[0]
            elif a:
                # if the attribute had no value.
                attr[prop.key] = a[0]
                changed_cols.add(prop.key)

    if len(changed_cols) == 0:
        # not changed, but we have relationships. check those too
        no_init = attributes.PASSIVE_NO_INITIALIZE
        for prop in obj_mapper.iterate_properties:
            if hasattr(prop, 'name'):
                # in case it's a proxy property (synonym), this is correct column name
                prop_name = prop.name
            else:
                # everything else
                prop_name = prop.key
            has_changes = attributes.get_history(obj, prop_name, passive=no_init).has_changes()
            if isinstance(prop, RelationshipProperty) and has_changes:
                for p in prop.local_columns:
                    if p.foreign_keys:
                        changed_cols.add(prop.key)
                        break

                if len(changed_cols) > 0:
                    break

    if len(changed_cols) == 0 and not deleted:
        return

    if (session.app.config.get('CHRONONAUT_REQUIRE_EXTRA_CHANGE_INFO', False) is True and not
            hasattr(g, '__version_extra_change_info__')):
        msg = ('Strict tracking is enabled and no g.__version_extra_change_info__ was found. '
               'Use the `extra_change_info` context manager before committing.')
        raise ChrononautException(msg)

    attr['version'] = obj.version or 0
    change_info = obj._capture_change_info()

    recorded_changes = fetch_recorded_changes()
    if recorded_changes is not None:
        change_info['extra'] = {}
        for key, val in recorded_changes.items():
            change_info['extra'][key] = val

    if len(changed_cols.intersection(hidden_cols)) > 0:
        change_info['hidden_cols_changed'] = list(changed_cols.intersection(hidden_cols))
    attr['change_info'] = change_info

    # update the history object (except any hidden cols)
    hist = history_cls()
    for key, value in attr.items():
        if key in hidden_cols:
            pass
        else:
            setattr(hist, key, value)

    session.add(hist)
    obj.version = attr['version'] + 1


@contextmanager
def extra_change_info(**kwargs):
    if _app_ctx_stack.top is None:
        raise ChrononautException('Can only use `extra_change_info` in a Flask app context.')
    setattr(g, '__version_extra_change_info__', kwargs)
    yield
    delattr(g, '__version_extra_change_info__')


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


__all__ = ['VersionedSQLAlchemy', 'VersionedSignallingSession', 'Versioned',
           'extra_change_info', 'ChrononautException']
