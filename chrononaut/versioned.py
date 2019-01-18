from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import mapper, object_mapper
from sqlalchemy.orm.exc import UnmappedColumnError

from chrononaut.change_info import ChangeInfoMixin
from chrononaut.exceptions import ChrononautException
from chrononaut.history_mapper import history_mapper


class Versioned(ChangeInfoMixin):
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
        # If the model has the RecordChanges mixin, only query the history table as needed
        if hasattr(self, '__chrononaut_record_change_info__'):
            if before is not None and self.changed > before:
                return [] if not return_query else self.query.filter(False)
            if after is not None and self.changed < after:
                return [] if not return_query else self.query.filter(False)

        # Get the primary keys for this table
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

    def previous_version(self):
        """Fetch the previous version of this model (or None)

        :return: A history model, or ``None`` if no history exists
        """
        query = self.versions(return_query=True)

        # order_by(None) resets order_by() called in versions()
        query = query.order_by(None).order_by(self.__history_mapper__.class_.version.desc())
        return query.first()

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
