"""Change info mixins. Require Flask for getting request and app context variables.
"""
import pytz
from datetime import datetime

from flask import current_app, g, request
from flask.globals import _app_ctx_stack, _request_ctx_stack
from sqlalchemy import Column, DateTime
from sqlalchemy.dialects import postgresql

from chrononaut.exceptions import ChrononautException
from chrononaut.flask_versioning import fetch_change_info


def _in_flask_context():
    if _app_ctx_stack.top is None or _request_ctx_stack.top is None:
        return False
    else:
        return True


class ChangeInfoMixin(object):
    """A mixin that the :class:`Versioned` mixin inherits from and includes change info tracking features.
    """
    @classmethod
    def _capture_change_info(cls):
        """Capture the change info for the new version. By default calls:

        (1) :meth:`_fetch_current_user_id` which should return a string or None; and
        (2) :meth:`_fetch_remote_addr` which should return an IP address string or None;
        (3) :meth:`_get_custom_change_info` which should return a 1-depth dict of additional keys.

        These 3 methods generate a ``change_info`` and with 2+ top-level keys (``user_id``,
        ``remote_addr``, and any keys from :meth:`_get_custom_change_info`)
        """
        change_info = {
            'user_id': cls._fetch_current_user_id(),
            'remote_addr': cls._fetch_remote_addr(),
        }
        extra_info = cls._get_custom_change_info()
        if extra_info:
            change_info.update(extra_info)
        return change_info

    @classmethod
    def _fetch_current_user_id(cls):
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

    @classmethod
    def _fetch_remote_addr(cls):
        """Return the IP address for the current user.

        :return: An IP address string or ``None`` if not available.
        """
        if not _in_flask_context():
            return None
        return request.remote_addr

    @classmethod
    def _get_custom_change_info(cls):
        """Optionally return additional ``change_info`` fields to be
        inserted into the history record. By default, this checks for a Flask app
        config variable `CHRONONAUT_EXTRA_CHANGE_INFO_FUNC` and calls the callable
        stored there (note that this may need to be wrapped with `staticfunction`).
        If not defined, returns no additional change info. Note that :class:`Versioned`
        may be subclassed to further refine how custom change info is generated and propagated.

        :return: A dictionary of additional ``change_info`` keys and values
        """
        extra_info = current_app.config.get('CHRONONAUT_EXTRA_CHANGE_INFO_FUNC')
        if extra_info:
            return extra_info()
        return None


class RecordChanges(ChangeInfoMixin):
    """A mixin that records change information in a ``change_info`` JSON column and a ``changed``
    timezone-aware datetime column. Creates change records in the same format as the :class:`Versioned`
    mixin, but stores them directly on the model vs. in a separate history table.
    """
    __chrononaut_record_change_info__ = True
    change_info = Column('change_info', postgresql.JSONB, default=None)
    changed = Column('changed', DateTime(timezone=True), default=lambda: datetime.now(pytz.utc))


def append_recorded_changes(obj, session):
    if (session.app.config.get('CHRONONAUT_REQUIRE_EXTRA_CHANGE_INFO', False) is True and not
            hasattr(g, '__version_extra_change_info__')):
        msg = ('Strict tracking is enabled and no g.__version_extra_change_info__ was found. '
               'Use the `extra_change_info` context manager before committing.')
        raise ChrononautException(msg)

    obj.change_info = fetch_change_info(obj)
    obj.changed = datetime.now(pytz.utc)


def increment_version_on_insert(obj):
    """Increments the version of the object to +1 after the last version in history. This will only
    ever be called when inserting a row into the table, and is only necessary when there may be
    primary key collisions on the main table in columns other than `version`.
    """
    history_model = obj.previous_version()

    if history_model is not None:
        obj.version = history_model.version + 1
