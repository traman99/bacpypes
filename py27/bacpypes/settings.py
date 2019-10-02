#!/usr/bin/python

"""
Settings
"""


class Settings(dict):
    def __getattr__(self, name):
        if name not in self:
            raise AttributeError("No such setting: " + name)
        return self[name]

    def __setattr__(self, name, value):
        if name not in self:
            raise AttributeError("No such setting: " + name)
        self[name] = value


# globals
settings = Settings(
    debug=set(),
    color=False,
    debug_file="",
    max_bytes=1048576,
    backup_count=5,
    route_aware=False,
)
