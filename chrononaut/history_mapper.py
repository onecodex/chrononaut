"""
Versioned mixin class and other utilities.


Partially derived from/see for reference:
http://docs.sqlalchemy.org/en/latest/orm/examples.html?highlight=version#module-examples.versioned_history
http://docs.sqlalchemy.org/en/latest/_modules/examples/versioned_history/test_versioning.html
http://docs.sqlalchemy.org/en/latest/_modules/examples/versioned_history/history_meta.html
"""
from datetime import datetime

import pytz
from sqlalchemy.orm import mapper
from sqlalchemy import Table, Column, ForeignKeyConstraint, Integer, DateTime
from sqlalchemy import util

from sqlalchemy.dialects import postgresql

# We need to ignore a warning here, as Flask-SQLAlchemy causes problems in its
# _should_set_tablename item run at init time
# See: https://github.com/mitsuhiko/flask-sqlalchemy/issues/349
from sqlalchemy.exc import SAWarning
import warnings
warnings.simplefilter('ignore', SAWarning)


def col_references_table(col, table):
    for fk in col.foreign_keys:
        if fk.references(table):
            return True
    return False


def history_mapper(local_mapper):
    cls = local_mapper.class_

    # set the "active_history" flag on on column-mapped attributes so that the old version
    # of the info is always loaded (we don't have to do this if we're not copying the values)
    # TODO: do we need to do this if we're forcing the load using get_attr in create_version?
    omit_cols = set(getattr(cls, '__version_omit__', []))
    for prop in local_mapper.iterate_properties:
        if prop.key not in omit_cols:
            getattr(cls, prop.key).impl.active_history = True

    super_mapper = local_mapper.inherits
    super_history_mapper = getattr(cls, '__history_mapper__', None)

    polymorphic_on = None
    super_fks = []

    def _col_copy(col):
        copy = col.copy()
        col.info['history_copy'] = copy
        copy.unique = False
        copy.default = None
        copy.server_default = None
        return copy

    # we don't create copies of these columns on the version table b/c we don't save them anyways
    hide_cols = set(getattr(cls, '__version_hide__', []))

    properties = util.OrderedDict()
    if not super_mapper or local_mapper.local_table is not super_mapper.local_table:
        cols = []
        # add column.info to identify columns specific to versioning
        version_meta = {"version_meta": True}

        for column in local_mapper.local_table.c:
            if 'version_meta' in column.info or column.key in hide_cols:
                continue

            col = _col_copy(column)

            if super_mapper and col_references_table(column, super_mapper.local_table):
                super_fks.append(
                    (col.key, list(super_history_mapper.local_table.primary_key)[0])
                )

            cols.append(col)

            if column is local_mapper.polymorphic_on:
                polymorphic_on = col

            orig_prop = local_mapper.get_property_by_column(column)
            # carry over column re-mappings
            if len(orig_prop.columns) > 1 or orig_prop.columns[0].key != orig_prop.key:
                properties[orig_prop.key] = tuple(col.info['history_copy']
                                                  for col in orig_prop.columns)

        if super_mapper:
            super_fks.append(('version', super_history_mapper.local_table.c.version))

        # "version" stores the integer version id.  This column is required.
        cols.append(
            Column('version', Integer, primary_key=True, autoincrement=False, info=version_meta)
        )

        # "changed" column stores the UTC timestamp of when the history row was created.
        # This column is optional and can be omitted.
        cols.append(
            Column('changed', DateTime, default=lambda: datetime.now(pytz.utc), info=version_meta)
        )

        # Append some JSON metadata about the change too
        cols.append(Column('change_info', postgresql.JSONB, default=None, info=version_meta))

        if super_fks:
            cols.append(ForeignKeyConstraint(*zip(*super_fks)))

        table = Table(local_mapper.local_table.name + '_history', local_mapper.local_table.metadata,
                      *cols, schema=local_mapper.local_table.schema)
    else:
        # single table inheritance.  take any additional columns that may have
        # been added and add them to the history table.
        for column in local_mapper.local_table.c:
            if column.key not in super_history_mapper.local_table.c:
                col = _col_copy(column)
                super_history_mapper.local_table.append_column(col)
        table = None

    if super_history_mapper:
        bases = (super_history_mapper.class_,)

        if table is not None:
            properties['changed'] = (
                (table.c.changed, ) + tuple(super_history_mapper.attrs.changed.columns)
            )
    else:
        bases = local_mapper.base_mapper.class_.__bases__
    versioned_cls = type.__new__(type, "%sHistory" % cls.__name__, bases, {})

    m = mapper(
        versioned_cls,
        table,
        inherits=super_history_mapper,
        polymorphic_on=polymorphic_on,
        polymorphic_identity=local_mapper.polymorphic_identity,
        properties=properties
    )
    cls.__history_mapper__ = m

    if not super_history_mapper:
        local_mapper.local_table.append_column(
            Column('version', Integer, default=0, nullable=True)
        )
        local_mapper.add_property("version", local_mapper.local_table.c.version)
