"""Flask versioning extension. Requires g and _app_ctx_stack in looking for extra recorded changes.
"""
from flask import g
from flask.globals import _app_ctx_stack
from datetime import datetime
from dateutil.tz import tzutc
import pytz
import six

from sqlalchemy.orm import attributes, object_mapper
from sqlalchemy.orm.exc import UnmappedColumnError
from sqlalchemy.orm.properties import RelationshipProperty

from chrononaut.exceptions import ChrononautException
from chrononaut.models import HistorySnapshot


UTC = tzutc()


def serialize_datetime(dt):
    dt.astimezone(UTC).replace(tzinfo=None).isoformat() + "Z"


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
        elif isinstance(val, six.string_types) or isinstance(val, int) or isinstance(val, bool):
            return val
        elif isinstance(val, datetime):
            return serialize_datetime(val)
        else:
            return str(val)

    if obj_mapper is None:
        obj_mapper = object_mapper(obj)
    obj_state = attributes.instance_state(obj)
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

            # expired object attributes and also deferred cols might not be in the dict.
            # force it to load no matter what by using getattr().
            if prop.key not in obj_state.dict:
                getattr(obj, prop.key)

            a, u, d = attributes.get_history(obj, prop.key)

            if d:
                attr[prop.key] = d[0]
                dirty_cols.add(prop.key)
            elif u:
                attr[prop.key] = u[0]
            elif a:
                # if the attribute had no value.
                attr[prop.key] = a[0]
                dirty_cols.add(prop.key)
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

    return HistorySnapshot(
        activity_obj.data,
        activity_obj.table_name,
        activity_obj.changed,
        activity_obj.user_info,
        activity_obj.extra_info,
        untracked_cols,
        hidden_cols,
    )


def create_version(obj, session, deleted=False):
    obj_mapper = object_mapper(obj)
    attrs, changed_cols = model_to_chrononaut_snapshot(obj, obj_mapper)

    if len(changed_cols) == 0:
        # not changed, but we have relationships. check those too
        no_init = attributes.PASSIVE_NO_INITIALIZE
        for prop in obj_mapper.iterate_properties:
            if hasattr(prop, "name"):
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

    # create the history object (except any hidden cols)
    activity = obj.metadata._activity_cls()

    activity.table_name = obj_mapper.local_table.name
    activity.data = attrs
    activity.changed = datetime.now(pytz.utc)
    activity.version = obj.version or 0
    activity.user_info = user_info
    activity.extra_info = extra_info

    session.add(activity)
    obj.version = activity.version + 1
