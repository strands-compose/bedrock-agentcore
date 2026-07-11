"""Hand-written fakes for transport seams.

Only the seams our code actually touches are faked here.  boto3 is driven
through ``botocore.Stubber`` (which validates request shapes against the real
service model) rather than a hand-rolled client fake, and ``httpx`` through
``httpx.MockTransport`` -- both live inline in the client tests.  This module
holds the one transport double with no vendor test seam: the ``urllib``
response object that ``LocalClient`` iterates.
"""

from __future__ import annotations


class FakeUrlResponse:
    """Stands in for the urllib response context manager.

    Provides iteration over pre-loaded byte lines -- the only protocol
    ``LocalClient`` uses on the ``urlopen`` return value.
    """

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc: object):
        pass

    def __iter__(self):
        return iter(self._lines)
