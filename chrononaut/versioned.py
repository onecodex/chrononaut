from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import mapper, object_mapper

from chrononaut.change_info import ChangeInfoMixin
from chrononaut.exceptions import ChrononautException
from chrononaut.history_mapper import extend_mapper
from chrononaut.flask_versioning import model_to_chrononaut_snapshot, chrononaut_snapshot_to_model
from datetime import datetime
import pytz


class Versioned(ChangeInfoMixin):
    """A mixin for use with Flask-SQLAlchemy declarative models. To get started, simply add
    the :class:`Versioned` mixin to one of your models::

        class User(db.Model, Versioned):
            __tablename__ = 'appuser'
            id = db.Column(db.Integer, primary_key=True)
            email = db.Column(db.String(255))
            ...

    The above will then automatically track updates to the ``User`` model and save
    value snapshots of prior versions of each record to the ``activity`` table. By default,
    *all* columns are tracked. By default, change information includes a ``user_id``
    and ``remote_addr``, which are set to automatically populate from Flask-Login's
    ``current_user`` in the :meth:`_capture_user_info` method. Subclass :class:`Versioned`
    and override a combination of :meth:`_capture_user_info`, :meth:`_fetch_current_user_id`,
    and :meth:`_get_custom_change_info`. This ``user_info`` is stored in a JSON column in your
    application's database and has the following rough layout::

        {
            "user_id": "A unique user ID (string) or None",
            "remote_addr": "The user IP (string) or None"
        }
    
    An additional ``extra_info`` column stores extra metadata associated with a version, like
    hidden columns that changed or manually appended data, i.e. ``rationale``::

        {
            "rationale": "..."
            "hidden_cols_changed": [
                ...  # A list of any hidden fields changed in the version
            ]
        }

    Note that the latter column will be an empty dictionary by default. You may
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
            extend_mapper(mp)
            return mp

        return map_function

    def versions(self, before=None, after=None, return_query=False):
        """Fetch the history of the given object from its history table.

        :param before: Return changes only _before_ the provided ``DateTime``.
        :param before: Return changes only _after_ the provided ``DateTime``.
        :param return_query: Return a SQLAlchemy query instead of a list of models.
        :return: List of HistorySnapshot models for the given object (or a query object).
        """
        # If the model has the RecordChanges mixin, only query the history table as needed
        if hasattr(self, "__chrononaut_record_change_info__"):
            if before is not None and self.changed > before:
                return [] if not return_query else self.query.filter(False)
            if after is not None and self.changed < after:
                return [] if not return_query else self.query.filter(False)

        activity = self.metadata._activity_cls
        mapper = object_mapper(self)

        # Get the primary keys for this table
        prim_keys = [k.key for k in mapper.primary_key if k.key != "version"]

        # Find all previous versions that have the same primary keys and table name as myself
        query = activity.query.filter(
            *[activity.data[k].astext.__eq__(str(getattr(self, k))) for k in prim_keys]
        ).filter(activity.table_name.__eq__(mapper.local_table.name))

        # Filter additionally by date as needed
        if before is not None:
            query = query.filter(activity.changed <= before)
        if after is not None:
            query = query.filter(activity.changed >= after)

        # Order by the version
        query = query.order_by(activity.version)

        if return_query:
            return query
        else:
            return [chrononaut_snapshot_to_model(self, m) for m in  query.all()]

    def version_at(self, at, return_snapshot=False):
        """Fetch the history model at a specific time (or None)

        :param at: The DateTime at which to find the history record.
        :param return_snapshot: Return just the object snapshot dict instead of the model.
        :return: The HistorySnapshot model representing the model at the given point in time
        or the model itself if that is current.
        """
        query = self.versions(after=at, return_query=True)
        history_model = query.first()

        if history_model is None:
            return self if not return_snapshot else model_to_chrononaut_snapshot(self)[0]
        else:
            return (
                history_model.data
                if return_snapshot
                else chrononaut_snapshot_to_model(self, history_model)
            )

    def has_changed_since(self, since):
        """Check if there are any changes since a given time.

        :param since: The DateTime from which to find any history records
        :return: ``True`` if there have been any changes. ``False`` if not.
        """
        # TODO: this is ambiguous, what if there were 2 changes which cancel each other out?
        return not len(self.diff(from_timestamp=since)) == 0

    def previous_version(self):
        """Fetch the previous version of this model (or None)

        :return: The HistorySnapshot model with attributes set to the previous state,
        or ``None`` if no history exists.
        """
        query = self.versions(return_query=True)
        activity = self.metadata._activity_cls

        # order_by(None) resets order_by() called in versions()
        query = query.order_by(None).order_by(activity.version.desc())
        history_model = query.first()
        return chrononaut_snapshot_to_model(self, history_model) if history_model else None

    def diff(self, from_timestamp, to_timestamp=None, include_hidden=False):
        """Enumerate the changes from a prior model state (at ``from_timestamp``) to a later
        model state or the current model's state (if ``to_timestamp`` is ``None``).

        :param from_timestamp: A point in time for the model to diff from.
        :param to_timestamp: A point in time to diff to or ``None`` for current version.
        :return: A dict of column names and ``(from, to)`` value tuples
        """
        if to_timestamp is None:
            to_timestamp = datetime.now(pytz.utc)

        if not isinstance(from_timestamp, datetime):
            raise ChrononautException("The diff method takes datetime as its argument.")

        if to_timestamp < from_timestamp:
            raise ChrononautException(
                "Diffs must be chronological. Your from_model post-dates your to."
            )

        from_dict = self.version_at(from_timestamp, return_snapshot=True)
        to_dict = self.version_at(to_timestamp, return_snapshot=True)

        hidden_cols = set(getattr(self, "__chrononaut_hidden__", []))
        all_keys = set(from_dict.keys())
        all_keys.update(to_dict.keys())
        all_keys = all_keys.difference(hidden_cols)

        diff = {}
        for k in all_keys:
            if k in from_dict and k not in to_dict:
                diff[k] = (from_dict[k], None)
            elif k not in from_dict and k in to_dict:
                diff[k] = (None, from_dict[k])
            else:
                # it's in both
                if from_dict[k] != to_dict[k]:
                    diff[k] = (from_dict[k], to_dict[k])

        # If `include_hidden` we need to enumerate through every
        # model *since* the from_timestamp *until* the to_timestamp
        # and see if `extra_info` includes hidden columns.
        if include_hidden:
            between_versions = self.versions(
                after=from_timestamp, before=to_timestamp, return_query=True
            )
            for version in between_versions.all():
                if "hidden_cols_changed" in version.extra_info:
                    for hidden_col in version.extra_info["hidden_cols_changed"]:
                        diff[hidden_col] = (None, to_dict[hidden_col])
                    break

        return diff
