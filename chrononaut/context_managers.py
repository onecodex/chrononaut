from contextlib import contextmanager

from flask import g, has_app_context

from chrononaut.exceptions import ChrononautException


@contextmanager
def extra_change_info(**kwargs):
    """A context manager for appending extra ``change_info`` into Chrononaut
    history records for :class:`Versioned` models. Supports appending
    changes to multiple individual objects of the same or varied classes.

    Usage::

        with extra_change_info(change_rationale='User request'):
            user.email = 'new-email@example.com'
            letter.subject = 'Welcome New User!'
            db.session.commit()

    Note that the ``db.session.commit()`` change needs to occur within the context manager block
    for additional fields to get injected into the history table ``extra_info`` JSON.
    Any number of keyword arguments with string values are supported.

    The above example yields a ``extra_info`` like the following::

        {
            "change_rationale": "User request"
        }
    """
    if not has_app_context():
        raise ChrononautException("Can only use `extra_change_info` in a Flask app context.")
    g.__version_extra_change_info__ = kwargs
    yield
    delattr(g, "__version_extra_change_info__")


@contextmanager
def rationale(rationale):
    """A simplified version of the :func:`extra_change_info` context manager that
    accepts only a rationale string and stores it in the extra change info.

    Usage::

        with rationale('Updating per user request, see GH #1732'):
            user.email = 'updated@example.com'
            db.session.commit()

    This would yield a ``extra_info`` like the following::

        {
            "rationale": "Updating per user request, see GH #1732"
        }
    """
    with extra_change_info(rationale=rationale):
        yield


@contextmanager
def append_change_info(obj, **kwargs):
    """A context manager for appending extra ``change`` info
    directly onto a single model instance. Use :func:`extra_change_info`
    for tracking multiple objects of the same or different classes.

    Usage::

        with append_change_info(user, change_rationale='User request'):
            user.email = 'new-email@example.com'
            db.session.commit()

    Note that ``db.session.commit()`` does *not* need to occur within the context manager
    block for additional fields to be appended. Changes take the same form as with
    :func:`extra_change_info`.
    """
    if not has_app_context():
        raise ChrononautException("Can only use `append_change_info` in a Flask app context.")

    if not hasattr(obj, "__versioned__"):
        raise ChrononautException("Cannot append_change_info to an object that is not Versioned.")

    obj.__CHRONONAUT_RECORDED_CHANGES__ = {}
    for key, val in kwargs.items():
        obj.__CHRONONAUT_RECORDED_CHANGES__[key] = val

    yield
