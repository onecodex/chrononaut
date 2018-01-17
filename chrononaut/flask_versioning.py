"""Flask versioning extension. Requires g and _app_ctx_stack in looking for extra recorded changes.
"""
from flask import g
from flask.globals import _app_ctx_stack

from sqlalchemy.orm import attributes, object_mapper
from sqlalchemy.orm.exc import UnmappedColumnError
from sqlalchemy.orm.properties import RelationshipProperty

from chrononaut.exceptions import ChrononautException


def fetch_change_info(obj):
    change_info = obj._capture_change_info()
    if _app_ctx_stack.top is None:
        return change_info

    extra_change_info = {}
    extra_change_info.update(getattr(g, '__version_extra_change_info__', {}))
    extra_change_info.update(getattr(obj, '__CHRONONAUT_RECORDED_CHANGES__', {}))
    if extra_change_info:
        change_info['extra'] = extra_change_info

    return change_info


def create_version(obj, session, deleted=False):
    obj_mapper = object_mapper(obj)
    history_mapper = obj.__history_mapper__
    history_cls = history_mapper.class_

    obj_state = attributes.instance_state(obj)

    attr = {}

    hidden_cols = set(getattr(obj, '__chrononaut_hidden__', []))
    untracked_cols = set(getattr(obj, '__chrononaut_untracked__', []))

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
    change_info = fetch_change_info(obj)

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
