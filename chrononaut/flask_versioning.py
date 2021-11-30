"""Flask versioning extension. Requires g and _app_ctx_stack in looking for extra recorded changes.
"""
from flask import g
from flask.globals import _app_ctx_stack
from datetime import datetime
from dateutil.tz import tzutc
import six
import numbers

from sqlalchemy import inspect
from sqlalchemy.orm import object_mapper
from sqlalchemy.orm.exc import UnmappedColumnError

from chrononaut.exceptions import ChrononautException
from chrononaut.models import HistorySnapshot


UTC = tzutc()


def serialize_datetime(dt):
    try:
        return dt.astimezone(UTC).replace(tzinfo=None).isoformat() + "+00:00"
    except TypeError:
        return dt.replace(tzinfo=None).isoformat() + "+00:00"


def _get_tracked_columns(obj, obj_mapper=None):
    """Returns a list of columns tracked by chrononaut. In case of db column name -> property
    name discrepancy, the property name is returned.
    """
    if obj_mapper is None:
        obj_mapper = object_mapper(obj)
    untracked_cols = set(getattr(obj, "__chrononaut_untracked__", []))
    tracked = []
    for om in obj_mapper.iterate_to_root():
        for obj_col in om.local_table.c:
            if (
                "version_meta" in obj_col.info
                or obj_col.key in untracked_cols
                or obj_col.key == "version"
            ):
                continue

            # Get the value of the attribute based on the MapperProperty related to the
            # mapped column.  this will allow usage of MapperProperties that have a
            # different keyname than that of the mapped column.
            try:
                prop = obj_mapper.get_property_by_column(obj_col)
            except UnmappedColumnError:
                # In the case of single table inheritance, there may be columns on the mapped
                # table intended for the subclass only. the "unmapped" status of the subclass
                # column on the base class is a feature of the declarative module.
                continue
            tracked.append(prop.key)
    return tracked


def _get_dirty_attributes(obj, state=None, check_relationships=False):
    """Returns a set of actually modified attributes sans attributes marked as untracked.

    "param obj: The object to be tested.
    :param state: (Optional) use this state object to investigate the state. If not provided, one
    will be inferred from obj.
    :param check_relationships: Whether the relationship attributes should be checked alongside of
    normally tracked attributes. This is necessary when checking in `before_flush` step where the
    foreign keys aren't yet set to their respective values.
    """
    if state is None:
        state = inspect(obj)
    unmodified = state.unmodified
    tracked_attrs = _get_tracked_columns(obj, state.mapper)
    dirty_cols = set()

    if check_relationships:
        relationships = [
            r.key
            for r in state.mapper.relationships
            if any(p.foreign_keys and p.key in tracked_attrs for p in r.local_columns)
        ]
        tracked_attrs.extend(relationships)

    candidates = [
        attr for attr in state.attrs if attr.key in tracked_attrs and attr.key not in unmodified
    ]
    for attr in candidates:
        a, _, d = attr.history
        if a or d:
            # Only add columns which values actually changed
            dirty_cols.add(attr.key)
    return dirty_cols


def fetch_change_info(obj):
    """Returns a user and extra info context for a change."""
    user_info = obj._capture_user_info()
    if _app_ctx_stack.top is None:
        return user_info, {}

    extra_change_info = obj._get_custom_change_info()
    extra_change_info.update(getattr(g, "__version_extra_change_info__", {}))
    extra_change_info.update(getattr(obj, "__CHRONONAUT_RECORDED_CHANGES__", {}))

    return user_info, extra_change_info


def is_modified(obj):
    """Returns whether an object was modified in a way that warrants a new chrononaut version."""
    return len(_get_dirty_attributes(obj, check_relationships=True)) > 0


def model_to_chrononaut_snapshot(obj, state=None):
    """Creates a Chrononaut snapshot (a dict) containing the object state.

    :param obj: The object to convert.
    :param state: (Optional) use this object state, otherwise one will be inferred from obj.
    :return The object state snapshot dict and a set of dirty columns.
    """

    def _default(val):
        if val is None:
            return None
        elif (
            isinstance(val, six.string_types)
            or isinstance(val, numbers.Real)
            or isinstance(val, bool)
        ):
            return val
        elif isinstance(val, datetime):
            return serialize_datetime(val)
        else:
            return str(val)

    if state is None:
        state = inspect(obj)

    tracked = _get_tracked_columns(obj, state.mapper)
    return {attr.key: _default(attr.value) for attr in state.attrs if attr.key in tracked}


def chrononaut_snapshot_to_model(model, activity_obj):
    """Creates a HistorySnapshot model based on a Chrononaut ActivityBase class.

    :param model: The base model the snapshot comes from.
    :param activity_obj: The Activity object containing the data to create a HistorySnapshot model.
    :return The HistorySnapshot model.
    """

    if not activity_obj.metadata or not isinstance(
        activity_obj, activity_obj.metadata._activity_cls
    ):
        raise ChrononautException("Can only recreate model based on Activity object")

    untracked_cols = set(getattr(model, "__chrononaut_untracked__", []))
    hidden_cols = set(getattr(model, "__chrononaut_hidden__", []))

    return HistorySnapshot(activity_obj, untracked_cols, hidden_cols)


def create_version(obj, session, created=False, deleted=False):
    if hasattr(g, "__suppress_versioning__"):
        return

    state = inspect(obj)
    changed_attrs = _get_dirty_attributes(obj, state)

    if len(changed_attrs) == 0 and not (deleted or created):
        return

    snapshot = model_to_chrononaut_snapshot(obj, state)

    if session.app.config.get(
        "CHRONONAUT_REQUIRE_EXTRA_CHANGE_INFO", False
    ) is True and not hasattr(g, "__version_extra_change_info__"):
        msg = (
            "Strict tracking is enabled and no g.__version_extra_change_info__ was found. "
            "Use the `extra_change_info` context manager before committing."
        )
        raise ChrononautException(msg)

    hidden_cols = set(getattr(obj, "__chrononaut_hidden__", []))
    user_info, extra_info = fetch_change_info(obj)

    if len(changed_attrs.intersection(hidden_cols)) > 0:
        extra_info["hidden_cols_changed"] = list(changed_attrs.intersection(hidden_cols))

    # removing hidden cols from data
    for key in hidden_cols:
        if key in snapshot:
            del snapshot[key]

    snapshot_version = obj.version if not created and obj.version else 0
    snapshot["version"] = snapshot_version

    # constructing the key
    obj_mapper = state.mapper
    primary_keys = [
        obj_mapper.get_property_by_column(k).key
        for k in obj_mapper.primary_key
        if k.key != "version"
    ]
    key = {k: getattr(obj, k) for k in primary_keys}

    # create the history object (except any hidden cols)
    activity = obj.metadata._activity_cls()

    activity.table_name = obj_mapper.local_table.name
    activity.key = key
    activity.data = snapshot
    activity.changed = datetime.now(UTC)
    activity.version = snapshot_version
    activity.user_info = user_info
    activity.extra_info = extra_info

    session.add(activity)
