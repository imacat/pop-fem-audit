# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/4
"""The shared utilities of the package."""


def format_duration(seconds: float) -> str:
    """Format an elapsed duration for the closing summary line.

    :param seconds: The elapsed duration, in seconds.
    :return: The duration formatted ``mm:ss``, or ``h:mm:ss``
        once it reaches one hour.
    """
    total: int = round(seconds)
    hours: int
    remainder: int
    hours, remainder = divmod(total, 3600)
    minutes: int
    secs: int
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
