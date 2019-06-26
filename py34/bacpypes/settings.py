#!/usr/bin/python

"""
Settings
"""

import os

# configuration file
ini_file = os.getenv('BACPYPES_INI', 'BACpypes.ini')

# debugging settings
debug = os.getenv('BACPYPES_DEBUG', '')
color = os.getenv('BACPYPES_COLOR', None)
max_bytes = int(os.getenv('BACPYPES_MAXBYTES', 1048576))
backup_count = int(os.getenv('BACPYPES_BACKUPCOUNT', 5))

# advanced routing
route_aware = bool(os.getenv('BACPYPES_ROUTEAWARE', False))

