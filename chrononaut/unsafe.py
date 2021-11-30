from contextlib import contextmanager

from flask import g, _app_ctx_stack
from chrononaut.exceptions import ChrononautException


@contextmanager
def suppress_versioning(allow_deleting_history=False):
    """A context manager for suppressing Chrononaut version entries. Proceed with extreme caution
    as historic data and/or audit info may be lost when within this context manager block.
    Set ``allow_deleting_history`` to also enable removing Chrononaut history entries::

        with suppress_versioning(allow_deleting_history=True):
            obj = Model.query.get(id)
            obj.versions()[1].delete(db.session)

    For completely removing an object along with its history records, use::

        with suppress_versioning(allow_deleting_history=True):
            obj = Model.query.get(id)
            for version in obj.versions():
                version.delete(db.session)
            db.session.delete(obj)
            db.session.commit()

    Do not nest this context manager. If possible, avoid using at all.
    """
    if _app_ctx_stack.top is None:
        raise ChrononautException("Can only use `suppress_versioning` in a Flask app context.")
    g.__suppress_versioning__ = True
    if allow_deleting_history:
        g.__allow_deleting_history__ = True
    try:
        yield
    finally:
        if allow_deleting_history:
            delattr(g, "__allow_deleting_history__")
        delattr(g, "__suppress_versioning__")
