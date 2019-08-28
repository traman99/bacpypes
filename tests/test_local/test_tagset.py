#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Test TagSet
-----------
"""

import unittest

from bacpypes.debugging import bacpypes_debugging, ModuleLogger
from bacpypes.local.object import IRI

# some debugging
_debug = 0
_log = ModuleLogger(globals())


@bacpypes_debugging
class TestIRI(unittest.TestCase):

    def test_resolve_iri(self):
        if _debug: TestIRI._debug("test_resolve_iri")

        base = IRI("http://a/b/c/d;p?q")
        for reliri, rslt in (
            # Normal examples.
            ("g:h", "g:h"),
            ("g", "http://a/b/c/g"),
            ("./g", "http://a/b/c/g"),
            ("g/", "http://a/b/c/g/"),
            ("/g", "http://a/g"),
            ("//g", "http://g"),
            ("?y", "http://a/b/c/d;p?y"),
            ("g?y", "http://a/b/c/g?y"),
            ("#s", "http://a/b/c/d;p?q#s"),
            ("g#s", "http://a/b/c/g#s"),
            ("g?y#s", "http://a/b/c/g?y#s"),
            (";x", "http://a/b/c/;x"),
            ("g;x", "http://a/b/c/g;x"),
            ("g;x?y#s", "http://a/b/c/g;x?y#s"),
            ("", "http://a/b/c/d;p?q"),
            (".", "http://a/b/c/"),
            ("./", "http://a/b/c/"),
            ("..", "http://a/b/"),
            ("../", "http://a/b/"),
            ("../g", "http://a/b/g"),
            ("../..", "http://a/"),
            ("../../", "http://a/"),
            ("../../g", "http://a/g"),
            # Although the following abnormal examples are unlikely to occur in
            # normal practice, all URI parsers should be capable of resolving them
            # consistently.
            ("../../../g", "http://a/g"),
            ("../../../../g", "http://a/g"),
            # Parsers must remove the dot-segments "." and ".." when they
            # are complete components of a path, but not when they are only part
            # of a segment.
            ("/./g", "http://a/g"),
            ("/../g", "http://a/g"),
            ("g.", "http://a/b/c/g."),
            (".g", "http://a/b/c/.g"),
            ("g..", "http://a/b/c/g.."),
            ("..g", "http://a/b/c/..g"),
            # Less likely are cases where the relative URI reference uses
            # unnecessary or nonsensical forms of the "." and ".." complete path
            # segments.
            ("./../g", "http://a/b/g"),
            ("./g/.", "http://a/b/c/g/"),
            ("g/./h", "http://a/b/c/g/h"),
            ("g/../h", "http://a/b/c/h"),
            ("g;x=1/./y", "http://a/b/c/g;x=1/y"),
            ("g;x=1/../y", "http://a/b/c/y"),
            # Some applications fail to separate the reference's query and/or
            # fragment components from a relative path before merging it with the base
            # path and removing dot-segments. This error is rarely noticed, since
            # typical usage of a fragment never includes the hierarchy ("/")
            # character, and the query component is not normally used within relative
            # references.
            ("g?y/./x", "http://a/b/c/g?y/./x"),
            ("g?y/../x", "http://a/b/c/g?y/../x"),
            ("g#s/./x", "http://a/b/c/g#s/./x"),
            ("g#s/../x", "http://a/b/c/g#s/../x"),
            # Some parsers allow the scheme name to be present in a relative URI
            # reference if it is the same as the base URI scheme. This is considered
            # to be a loophole in prior specifications of partial URI [RFC1630]. Its
            # use should be avoided, but is allowed for backward compatibility.
            # ("http:g", "http:g"),         # TODO: for strict parsers
            ("http:g", "http://a/b/c/g"),   # for backward compatibility
        ):
            z = base.resolve(reliri)
            assert str(z) == rslt
