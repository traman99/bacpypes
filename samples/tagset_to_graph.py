#!/usr/bin/python

"""
TagSet To Graph
"""

import re
import base64

from rdflib import Graph, Literal, BNode, URIRef
from rdflib.namespace import Namespace, RDF, XSD

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
from bacpypes.basetypes import EngineeringUnits, DateTime
from bacpypes.local.object import IRI, ArrayOfNameValue

# enumeration names are analog-value rather that analogValue
_wordsplit_re = re.compile(r"([a-z0-9])([A-Z])(?=.)")

def _wordsplit(k):
    return _wordsplit_re.sub(lambda m: m.groups()[0] + "-" + m.groups()[1].lower(), k)

#
#
#

BACnetNS = Namespace("http://data.ashrae.org/bacnet/2016#")

def boolean_to_literal(value):
    return Literal(value.value, datatype=XSD.boolean)


def unsigned_to_literal(value):
    return Literal(value.value, datatype=XSD.nonNegativeInteger)


def integer_to_literal(value):
    return Literal(value.value, datatype=XSD.integer)


def real_to_literal(value):
    return Literal(value.value, datatype=XSD.float)


def double_to_literal(value):
    return Literal(value.value, datatype=XSD.double)


def octetstring_to_literal(value):
    base64_string = base64.b64encode(value.value)
    return Literal(base64_string, datatype=XSD.base64Binary)


def characterstring_to_literal(value):
    return Literal(value.value)


def bitstring_to_literal(value):
    bit_string = "".join(str(bit) for bit in value.value)
    return Literal(bit_string, datatype=BACnetNS.BitString)


def enumerated_to_literal(value):
    if isinstance(value.value, int):
        return Literal(str(value.value))
    else:
        return Literal(_wordsplit(value.value))


def date_to_literal(value):
    if value.is_special():
        return Literal(str(value), datatype=BACnetNS.Date)
    else:
        date_string = "{:04d}-{:02d}-{:02d}".format(
            value.value[0] + 1900, value.value[1], value.value[2]
        )
        return Literal(date_string, datatype=XSD.date, normalize=False)


def time_to_literal(value):
    time_string = str(value)

    if value.is_special():
        return Literal(time_string, datatype=BACnetNS.Time)
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
        return Literal(datetime_string, datatype=BACnetNS.DateTime, normalize=False)


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


def term_to_node(term, prefixes):
    uriref = IRI(term)
    if uriref.is_prefix():
        raise ValueError("local name, prefixed name, or IRI required")

    # resolve local and prefixed names
    if uriref.is_local_name():
        node = URIRef(prefixes[None] + term)
    elif uriref.is_prefixed_name():
        prefix, suffix = term.split(':', 1)
        if prefix == "_":
            node = BNode(suffix)
        elif (prefix in prefixes) and (not suffix.startswith('//')):
            node = URIRef(prefixes[prefix] + suffix)
        else:
            node = URIRef(term)

    return node


def elements_to_graph(element_list):
    objid = base = vocab = language = None

    # build a dictionary of the stuff for easier reference
    tag_set = {k: v for k, v in element_list}

    # pull out the language if there is one
    language = tag_set.pop("@language", None)
    if language:
        language = language.value

    # pull out the base or use the default
    base = tag_set.pop("@base", None)
    if base:
        base_iri = IRI(base.value)
    else:
        base_iri = IRI(str(BACnetNS))
    print("base: {}".format(base))

    # pull out the vocabulary and resolve against the base
    vocab = tag_set.pop("@vocab", None)
    if vocab:
        vocab_iri = base_iri.resolve(vocab.value)
    else:
        vocab_iri = base_iri
    prefixes = {None: str(vocab_iri)}

    # look for namespace prefix definitions and resolve with vocabulary
    for term in tag_set:
        if term.endswith(":"):
            prefix_name = term[:-1]
            prefix_value = tag_set[term].value
            prefixes[prefix_name] = str(vocab_iri.resolve(prefix_value))

    print("prefixes: {!r}".format(prefixes))

    # pull out the id or default to a blank node
    objid = tag_set.pop("@id", None)
    if objid:
        subject_ = term_to_node(objid.value, prefixes)
    else:
        subject_ = BNode()

    graph = Graph()
    for term, value in tag_set.items():
        if term[0] == "@" or term.endswith(":"):
            continue
        print("term: {!r}".format(term))
        print("value: {!r}".format(value))

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
        print("s, p, o: {!r}".format(statement_))
        print("")

        graph.add(statement_)

    return graph


test_elements = [
    ('@base', CharacterString("http://cornell.edu/snork")),
    ('@vocab', CharacterString("./arf#")),
    ('@id', CharacterString('_:3.1')),
    ('temp', Null()),
    #   (':', CharacterString("http://demo.org/")),
    #   (':sensor', Null()),
    #   ('statusEnable', Boolean(False)),
    #   ('p:', CharacterString("../bx#")),
    #   ('p:statusLimit', Unsigned(10)),
    #   ('elem', Real(12.3)),
    #   ('elem', Double(45.6)),
    #   ('elem', OctetString(b'0123')),
    #   ('//welcome', CharacterString("Hello, world!")),
    #   ('statusFlags', BitString([0, 1, 0, 1, 1])),
    #   ('units', Enumerated(63)),  # degreesKelvin
    ('units', EngineeringUnits(63)),
    #   ('startDate', Date().now()),
    #   ('startTime', Time().now()),
    #   ("spid", ObjectIdentifier("analogValue:3")),
    ("spref", CharacterString("<_:zook>")),
    ("spx", CharacterString("<_:zook>")),
    #   ('dateTime', DateTime(date=Date().now(), time=Time().now())),
]

graph = elements_to_graph(test_elements)


# Serialize as XML
if 0:
    print("--- start: rdf-xml ---")
    print(graph.serialize(format="pretty-xml").decode("utf-8"))
    print("--- end: rdf-xml ---\n")

# Serialize as Turtle
if 1:
    print("--- start: turtle ---")
    print(graph.serialize(format="turtle").decode("utf-8"))
    print("--- end: turtle ---\n")

# Serialize as NTriples
if 1:
    print("--- start: ntriples ---")
    print(graph.serialize(format="nt").decode("utf-8"))
    print("--- end: ntriples ---\n")

# Serialize as JSON-LD
if 0:
    print("--- start: json-ld ---")
    print(graph.serialize(format="json-ld").decode("utf-8"))
    print("--- end: json-ld ---\n")

# Serialize as JSON-LD with context
if 0:
    print("--- start: json-ld with context ---")
    context = {"@language": "en", "@base": BACnetNS, "@vocab": ""}
    result = graph.serialize(format="json-ld", context=context)
    print(result.decode("utf-8"))
    print("--- end: json-ld ---\n")
