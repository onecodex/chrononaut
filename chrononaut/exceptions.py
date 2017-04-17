"""Custom Exceptions raised by History Models
"""


class ChrononautException(Exception):
    pass


class UntrackedAttributeError(ChrononautException, AttributeError):
    pass


class HiddenAttributeError(ChrononautException, AttributeError):
    pass
