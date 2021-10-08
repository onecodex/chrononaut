"""Flask versioning extension. Requires g and _app_ctx_stack in looking for extra recorded changes.
"""
from flask import g
from flask.globals import _app_ctx_stack
from datetime import datetime
from dateutil.tz import tzutc
import six
import numbers

from sqlalchemy.orm import attributes, object_mapper
from sqlalchemy.orm.exc import UnmappedColumnError

from chrononaut.exceptions import ChrononautException
from chrononaut.models import HistorySnapshot


UTC = tzutc()


def serialize_datetime(dt):
    return dt.astimezone(UTC).replace(tzinfo=None).isoformat() + "+00:00"


def fetch_change_info(obj):
    user_info = obj._capture_user_info()
    if _app_ctx_stack.top is None:
        return user_info, {}

    extra_change_info = obj._get_custom_change_info()
    extra_change_info.update(getattr(g, "__version_extra_change_info__", {}))
    extra_change_info.update(getattr(obj, "__CHRONONAUT_RECORDED_CHANGES__", {}))

    return user_info, extra_change_info


def model_to_chrononaut_snapshot(obj, obj_mapper=None):
    """Creates a Chrononaut snapshot (a dict) containing the object state
    and a list of dirty columns.

    :param obj: The object to convert.
    :param obj_mapper: (Optional) use this mapper, otherwise one will be inferred from obj.
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

    if obj_mapper is None:
        obj_mapper = object_mapper(obj)
    untracked_cols = set(getattr(obj, "__chrononaut_untracked__", []))

    attr = {}
    dirty_cols = set()

    for om in obj_mapper.iterate_to_root():
        for obj_col in om.local_table.c:
            if "version_meta" in obj_col.info or obj_col.key in untracked_cols:
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

            attr[obj_col.name] = getattr(obj, prop.key)

            a, _, d = attributes.get_history(
                obj, prop.key, passive=attributes.PASSIVE_NO_INITIALIZE
            )
            if prop.key != "version" and (d or a):
                dirty_cols.add(obj_col.name)

    values = {k: _default(v) for k, v in attr.items()}
    return values, dirty_cols


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
    obj_mapper = object_mapper(obj)
    attrs, changed_cols = model_to_chrononaut_snapshot(obj, obj_mapper)

    if len(changed_cols) == 0 and not (deleted or created):
        return

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

    if len(changed_cols.intersection(hidden_cols)) > 0:
        extra_info["hidden_cols_changed"] = list(changed_cols.intersection(hidden_cols))

    # removing hidden cols from data
    for key in hidden_cols:
        del attrs[key]

    if not created:
        obj.version = obj.version + 1
        attrs["version"] = obj.version

    # constructing the key
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
    activity.data = attrs
    activity.changed = datetime.now(UTC)
    activity.version = 0 if created or not obj.version else obj.version
    activity.user_info = user_info
    activity.extra_info = extra_info

    session.add(activity)
