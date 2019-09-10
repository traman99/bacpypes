#!/usr/bin/python

"""
TagSet To Graph
"""

import re
import base64

from rdflib import Graph, Literal, BNode, URIRef
from rdflib.namespace import Namespace, RDF, XSD

from bacpypes.debugging import bacpypes_debugging, ModuleLogger
from bacpypes.consolelogging import ArgumentParser

from bacpypes.primitivedata import (
    Null,
    Boolean,
    Unsigned,
    Integer,
    Real,
    Double,
    OctetString,
    CharacterString,
    BitString,
    Enumerated,
    Date,
    Time,
    ObjectIdentifier,
)
from bacpypes.basetypes import EngineeringUnits, EventTransitionBits, DateTime
from bacpypes.local.object import IRI, ArrayOfNameValue

# some debugging
_debug = 0
_log = ModuleLogger(globals())

DefaultNS = Namespace("http://data.ashrae.org/223/2019#")

# enumeration names are analog-value rather that analogValue
_wordsplit_re = re.compile(r"([a-z0-9])([A-Z])(?=.)")


def _wordsplit(k):
    return _wordsplit_re.sub(lambda m: m.groups()[0] + "-" + m.groups()[1].lower(), k)


#
#
#


def boolean_to_literal(value):
    return Literal(value.value, datatype=XSD.boolean)


def unsigned_to_literal(value):
    return Literal(value.value, datatype=XSD.nonNegativeInteger)


def integer_to_literal(value):
    return Literal(value.value, datatype=XSD.integer)


def real_to_literal(value):
    return Literal(value.value, datatype=XSD.float)  # XSD.decimal


def double_to_literal(value):
    return Literal(value.value, datatype=XSD.double)


def octetstring_to_literal(value):
    base64_string = base64.b64encode(value.value)
    return Literal(base64_string, datatype=XSD.base64Binary)


def characterstring_to_literal(value):
    return Literal(value.value)


@bacpypes_debugging
def bitstring_to_literal(value):
    if _debug:
        bitstring_to_literal._debug("bitstring_to_literal %r", value)

    # flip the bit names
    bit_names = {}
    for name, bit in value.bitNames.items():
        bit_names[bit] = _wordsplit(name)
    if _debug:
        bitstring_to_literal._debug("    - bit_names: %r", bit_names)

    # build a list of values and/or names
    value_names = [
        bit_names.get(bit_number, str(bit_number))
        for bit_number, bit in enumerate(value.value)
        if bit
    ]
    if _debug:
        bitstring_to_literal._debug("    - value_names: %r", value_names)

    # bundle it together
    return Literal(";".join(value_names))


def enumerated_to_literal(value):
    if isinstance(value.value, int):
        return Literal(str(value.value))
    else:
        return Literal(_wordsplit(value.value))


def date_to_literal(value):
    if value.is_special():
        return Literal(str(value), datatype=DefaultNS.Date)
    else:
        date_string = "{:04d}-{:02d}-{:02d}".format(
            value.value[0] + 1900, value.value[1], value.value[2]
        )
        return Literal(date_string, datatype=XSD.date, normalize=False)


def time_to_literal(value):
    time_string = str(value)

    if value.is_special():
        return Literal(time_string, datatype=DefaultNS.Time)
    else:
        return Literal(time_string, datatype=XSD.time, normalize=False)


def objectidentifier_to_literal(value):
    obj_type, obj_instance = value.value
    if isinstance(obj_type, int):
        obj_type_str = str(obj_type)
    else:
        obj_type_str = _wordsplit(obj_type)
    obj_instance_str = str(obj_instance)
    return Literal(obj_type_str + "." + obj_instance_str)


def datetime_to_literal(value):
    date, time = value.date, value.time

    if (not date.is_special()) and (not time.is_special()):
        date_string = "{:04d}-{:02d}-{:02d}".format(
            date.value[0] + 1900, date.value[1], date.value[2]
        )
        datetime_string = "{}T{}".format(date_string, str(time))
        return Literal(datetime_string, datatype=XSD.dateTime, normalize=False)
    else:
        datetime_string = "{}T{}".format(str(date), str(time))
        return Literal(datetime_string, datatype=DefaultNS.DateTime, normalize=False)


atomic_to_literal_map = {
    Boolean: boolean_to_literal,
    Unsigned: unsigned_to_literal,
    Integer: integer_to_literal,
    Real: real_to_literal,
    Double: double_to_literal,
    OctetString: octetstring_to_literal,
    CharacterString: characterstring_to_literal,
    BitString: bitstring_to_literal,
    Enumerated: enumerated_to_literal,
    Date: date_to_literal,
    Time: time_to_literal,
    ObjectIdentifier: objectidentifier_to_literal,
    DateTime: datetime_to_literal,
}


def elements_to_aonv(element_list):
    aonv = ArrayOfNameValue()
    for k, v in element_list:
        aonv.add(k, v)
    return aonv


def elements_to_dict(element_list):
    return {k: v for k, v in element_list}


@bacpypes_debugging
def term_to_node(term, prefixes):
    if _debug:
        term_to_node._debug("term_to_node %r %r", term, prefixes)

    uriref = IRI(term)
    if uriref.is_prefix():
        raise ValueError("local name, prefixed name, or IRI required")

    # resolve local and prefixed names
    if uriref.is_local_name():
        node = URIRef(prefixes[None] + term)
    elif uriref.is_prefixed_name():
        prefix, suffix = term.split(":", 1)
        if prefix == "_":
            node = BNode(suffix)
        elif (prefix in prefixes) and (not suffix.startswith("//")):
            node = URIRef(prefixes[prefix] + suffix)
        else:
            node = URIRef(term)
    if _debug:
        term_to_node._debug("    - node: %r", node)

    return node


@bacpypes_debugging
def elements_to_graph(device_element_list, object_element_list):
    if _debug:
        elements_to_graph._debug(
            "elements_to_graph %r %r", device_element_list, object_element_list
        )

    base_iri = vocab_iri = language = None

    # start with an empty graph
    graph = Graph()

    # register the BACnet namespace
    # graph.bind("a", DefaultNS)

    # build a prefix map by resolving the IRIs
    prefixes = {}

    for element_list in (device_element_list, object_element_list):
        # build a dictionary of the stuff for easier reference
        tag_set = {k: v for k, v in element_list}

        # pull out the base or use the default
        if "@base" in tag_set:
            base_iri = IRI(tag_set.pop("@base").value)
        elif not base_iri:
            base_iri = IRI(str(DefaultNS))
        if _debug:
            elements_to_graph._debug("    - base_iri: %s", base_iri)

        # pull out the vocabulary and resolve against the base
        if "@vocab" in tag_set:
            vocab_iri = base_iri.resolve(tag_set.pop("@vocab").value)
        else:
            vocab_iri = base_iri
        if _debug:
            elements_to_graph._debug("    - vocab_iri: %s", vocab_iri)

        # pull out the language if there is one
        if "@language" in tag_set:
            language = tag_set.pop("@language").value
        if _debug:
            elements_to_graph._debug("    - language: %r", language)

        # look for namespace prefix definitions and resolve with vocabulary
        for term in tag_set:
            if term.endswith(":"):
                prefix_name = term[:-1]
                prefix_value = tag_set[term].value
                prefix_iri = vocab_iri.resolve(prefix_value)
                prefix_str = str(prefix_iri)

                # tuck this away for term_to_node
                prefixes[prefix_name] = prefix_str

                # add it to the namespace manager for the graph
                graph.bind(prefix_name, Namespace(prefix_str))

    # set the default vocabulary for local (non-prefixed) names
    prefixes[None] = str(vocab_iri)
    if _debug:
        elements_to_graph._debug("    - prefixes: %r", prefixes)

    # pull out the id or default to a blank node
    objid = tag_set.pop("@id", None)
    if objid:
        subject_ = term_to_node(objid.value, prefixes)
    else:
        subject_ = BNode()
    if _debug:
        elements_to_graph._debug("    - subject_: %r", subject_)

    for term, value in tag_set.items():
        if term[0] == "@" or term.endswith(":"):
            continue
        if _debug:
            elements_to_graph._debug("    - term, value: %r, %r", term, value)

        predicate_ = term_to_node(term, prefixes)
        if isinstance(value, Null):
            object_ = predicate_
            predicate_ = RDF.type
        elif isinstance(value, CharacterString):
            str_value = value.value
            if str_value.startswith("<") and str_value.endswith(">"):
                object_ = term_to_node(str_value[1:-1], prefixes)
            elif language:
                object_ = Literal(str_value, lang=language)
            else:
                object_ = Literal(str_value)
        else:
            value_type = type(value)
            if value_type not in atomic_to_literal_map:
                for value_type in atomic_to_literal_map:
                    if isinstance(value, value_type):
                        break
                else:
                    raise TypeError("invalid type: %r" % (value_type,))
            object_ = atomic_to_literal_map[value_type](value)

        statement_ = (subject_, predicate_, object_)
        if _debug:
            elements_to_graph._debug("    - statement_: %r", statement_)

        graph.add(statement_)

    return graph


#
#   __main__
#

device_element_list = [
    # ('@base', CharacterString("http://sample.org/")),
    # ("@vocab", CharacterString("http://sample.org/")),
    # ('@language', CharacterString("en")),
    # (":", CharacterString("snerm#")),
]

object_element_list = [
    # ('@base', CharacterString("http://sample.org/")),
    # ("@vocab", CharacterString("snork#")),
    # ('@language', CharacterString("en")),
    # ('@id', CharacterString('_:3.1')),
    ("temp", Null()),
    # (':', CharacterString("http://example.org/")),
    # (":sensor", Null()),
    # (':inhibit-delay', Boolean(True)),
    # (':time-duration', Unsigned(12)),
    # (':high-offset', Integer(10)),
    # (':low-offset', Integer(-15)),
    # (':deadband', Real(0.5)),
    # (':parsecs', Double(12.5)),
    # (':key', OctetString(b'0123')),
    # (':welcome', CharacterString("Hello, world!")),
    # ('event-enable', EventTransitionBits([1, 0, 1])),
    # ('BACnet:', CharacterString("http://data.ashrae.org/bacnet/2016#")),
    # ('BACnet:units', CharacterString("<BACnet:degrees-kelvin>")),
    # ('statusLimit', Unsigned(10)),
    ('lowerBound', Real(12.3)),
    ('upperBound', Double(45.6)),
    # ('packedInfo', OctetString(b'0123')),
    ('welcomeMessage', CharacterString("Hello, world!")),
    # ('event-enable', EventTransitionBits([1, 0, 1])),
    # ('units', Enumerated(63)),  # degreesKelvin
    # ('units', EngineeringUnits(63)),
    # ('startDate', Date().now()),
    # ('startTime', Time().now()),
    # ("spid", ObjectIdentifier("analogValue:3")),
    # ("spref", CharacterString("<_:zook>")),
    # ("spx", CharacterString("<_:zook>")),
    # ('dateTime', DateTime(date=Date().now(), time=Time().now())),
]


def main():
    # parse the command line arguments
    parser = ArgumentParser(description=__doc__)

    # different output formats
    parser.add_argument("--rdf-xml", action="store_true", default=False, help="RDF/XML")
    parser.add_argument(
        "--turtle", action="store_true", default=False, help="Turtle output"
    )
    parser.add_argument(
        "--ntriples", action="store_true", default=False, help="N-Triples output"
    )
    parser.add_argument(
        "--json-ld", action="store_true", default=False, help="JSON-LD output"
    )
    parser.add_argument("--json-ld-context", type=str, help="JSON-LD with a context")

    # parse the command line arguments
    args = parser.parse_args()

    if _debug:
        _log.debug("initialization")
    if _debug:
        _log.debug("    - args: %r", args)

    graph = elements_to_graph(device_element_list, object_element_list)

    # Serialize as XML
    if args.rdf_xml:
        print(graph.serialize(format="pretty-xml").decode("utf-8"))

    # Serialize as Turtle
    if args.turtle:
        print(graph.serialize(format="turtle").decode("utf-8"))

    # Serialize as NTriples
    if args.ntriples:
        print(graph.serialize(format="nt").decode("utf-8"))

    # Serialize as JSON-LD
    if args.json_ld:
        print(graph.serialize(format="json-ld").decode("utf-8"))

    # Serialize as JSON-LD with context
    if args.json_ld_context:
        context = eval(
            args.json_ld_context
        )  # '{"@vocab": "http://data.ashrae.org/223/2019#"}'
        result = graph.serialize(format="json-ld", context=context)
        print(result.decode("utf-8"))


if __name__ == "__main__":
    main()
