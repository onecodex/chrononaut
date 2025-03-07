"""Change info mixins. Require Flask for getting request and app context variables."""

from datetime import datetime

from flask import current_app, g, request, has_request_context, has_app_context
from sqlalchemy import Column, DateTime
from sqlalchemy.dialects import postgresql

from chrononaut.exceptions import ChrononautException
from chrononaut.flask_versioning import fetch_change_info
from chrononaut.flask_versioning import UTC


class ChangeInfoMixin(object):
    """A mixin that the :class:`Versioned` mixin inherits from and includes change info tracking
    features.
    """

    @classmethod
    def _capture_user_info(cls):
        """Capture the user info for the new version. By default calls:

        (1) :meth:`_fetch_current_user_id` which should return a string or None; and
        (2) :meth:`_fetch_remote_addr` which should return an IP address string or None;

        These 2 methods generate a ``user_info`` with 2 top-level keys (``user_id``,
        ``remote_addr``)
        """
        return {
            "user_id": cls._fetch_current_user_id(),
            "remote_addr": cls._fetch_remote_addr(),
        }

    @classmethod
    def _fetch_current_user_id(cls):
        """Return the current user ID.

        :return: A unique user ID string or ``None`` if not available.
        """
        if not has_app_context():
            return None

        try:
            from flask_login import current_user

            return current_user.email if current_user.is_authenticated else None
        except (ImportError, AttributeError):
            return None

    @classmethod
    def _fetch_remote_addr(cls):
        """Return the IP address for the current user.

        :return: An IP address string or ``None`` if not available.
        """
        if not has_request_context():
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

        :return: A dictionary of additional ``change_info`` keys and values or an empty dict
        """
        extra_info = current_app.config.get("CHRONONAUT_EXTRA_CHANGE_INFO_FUNC")
        if extra_info:
            return extra_info()
        return {}


class RecordChanges(ChangeInfoMixin):
    """A mixin that records change information in a ``change_info`` JSON column and a ``changed``
    timezone-aware datetime column. Creates change records in the same format as the
    :class:`Versioned` mixin, but stores them directly on the model vs. in a separate history table.
    """

    __chrononaut_record_change_info__ = True
    change_info = Column("change_info", postgresql.JSONB, default=None)
    changed = Column("changed", DateTime(timezone=True), default=lambda: datetime.now(UTC))


def append_recorded_changes(obj):
    if current_app.config.get(
        "CHRONONAUT_REQUIRE_EXTRA_CHANGE_INFO", False
    ) is True and not hasattr(g, "__version_extra_change_info__"):
        msg = (
            "Strict tracking is enabled and no g.__version_extra_change_info__ was found. "
            "Use the `extra_change_info` context manager before committing."
        )
        raise ChrononautException(msg)

    # backwards compatibility workaround: generate a {'user_id', 'remote_addr', 'extra'} structure
    user_info, extra_info = fetch_change_info(obj)
    change_info = user_info
    if extra_info:
        change_info["extra"] = extra_info

    obj.change_info = change_info
    obj.changed = datetime.now(UTC)


def increment_version_on_insert(obj):
    """Increments the version of the object to +1 after the last version in history. This will only
    ever be called when inserting a row into the table, and is only necessary when there may be
    primary key collisions on the main table in columns other than `version`.
    """
    history_model = obj.previous_version()

    if history_model is not None:
        obj.version = history_model.version + 1
