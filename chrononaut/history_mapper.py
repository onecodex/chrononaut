from sqlalchemy import Column, Integer


def extend_mapper(local_mapper):
    for prop in local_mapper._props:
        local_mapper._props[prop].active_history = True

    for om in local_mapper.iterate_to_root():
        if "version" in om.columns:
            return

    local_mapper.local_table.append_column(Column("version", Integer, default=0, nullable=True))
    local_mapper.add_property("version", local_mapper.local_table.c.version)
