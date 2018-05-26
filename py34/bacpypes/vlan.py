#!/usr/bin/python

"""
Virtual Local Area Network
"""

import random
import socket
import struct
from copy import deepcopy

from .errors import ConfigurationError
from .debugging import ModuleLogger, bacpypes_debugging

from .pdu import Address, IPv4Address
from .comm import Client, Server, bind
from .task import OneShotFunction

# some debugging
_debug = 0
_log = ModuleLogger(globals())

#
#   Network
#

@bacpypes_debugging
class Network:

    def __init__(self, name='', broadcast_address=None, drop_percent=0.0):
        if _debug: Network._debug("__init__ name=%r broadcast_address=%r drop_percent=%r", name, broadcast_address, drop_percent)

        self.name = name
        self.nodes = []

        self.broadcast_address = broadcast_address
        self.drop_percent = drop_percent

        # point to a TrafficLog instance
        self.traffic_log = None

    def add_node(self, node):
        """ Add a node to this network, let the node know which network it's on. """
        if _debug: Network._debug("add_node %r", node)

        self.nodes.append(node)
        node.lan = self

        # update the node name
        if not node.name:
            node.name = '%s:%s' % (self.name, node.address)

    def remove_node(self, node):
        """ Remove a node from this network. """
        if _debug: Network._debug("remove_node %r", node)

        self.nodes.remove(node)
        node.lan = None

    def process_pdu(self, pdu):
        """ Process a PDU by sending a copy to each node as dictated by the
            addressing and if a node is promiscuous.
        """
        if _debug: Network._debug("process_pdu(%s) %r", self.name, pdu)

        # if there is a traffic log, call it with the network name and pdu
        if self.traffic_log:
            self.traffic_log(self.name, pdu)

        # randomly drop a packet
        if self.drop_percent != 0.0:
            if (random.random() * 100.0) < self.drop_percent:
                if _debug: Network._debug("    - packet dropped")
                return

        if pdu.pduDestination == self.broadcast_address:
            if _debug: Network._debug("    - broadcast")
            for node in self.nodes:
                if (pdu.pduSource != node.address):
                    if _debug: Network._debug("    - match: %r", node)
                    node.response(deepcopy(pdu))
        else:
            if _debug: Network._debug("    - unicast")
            for node in self.nodes:
                if node.promiscuous or (pdu.pduDestination == node.address):
                    if _debug: Network._debug("    - match: %r", node)
                    node.response(deepcopy(pdu))

    def __len__(self):
        """ Simple way to determine the number of nodes in the network. """
        return len(self.nodes)

#
#   Node
#

@bacpypes_debugging
class Node(Server):

    def __init__(self, addr, lan=None, name='', promiscuous=False, spoofing=False, sid=None):
        if _debug:
            Node._debug("__init__ %r lan=%r name=%r, promiscuous=%r spoofing=%r sid=%r",
                addr, lan, name, promiscuous, spoofing, sid
                )
        Server.__init__(self, sid)

        self.lan = None
        self.address = addr
        self.name = name

        # bind to a lan if it was provided
        if lan is not None:
            self.bind(lan)

        # might receive all packets and might spoof
        self.promiscuous = promiscuous
        self.spoofing = spoofing

    def bind(self, lan):
        """bind to a LAN."""
        if _debug: Node._debug("bind %r", lan)

        lan.add_node(self)

    def indication(self, pdu):
        """Send a message."""
        if _debug: Node._debug("indication(%s) %r", self.name, pdu)

        # make sure we're connected
        if not self.lan:
            raise ConfigurationError("unbound node")

        # if the pduSource is unset, fill in our address, otherwise
        # leave it alone to allow for simulated spoofing
        if pdu.pduSource is None:
            pdu.pduSource = self.address
        elif (not self.spoofing) and (pdu.pduSource != self.address):
            raise RuntimeError("spoofing address conflict")

        # actual network delivery is a zero-delay task
        OneShotFunction(self.lan.process_pdu, pdu)

    def __repr__(self):
        return "<%s(%s) at %s>" % (
            self.__class__.__name__,
            self.name,
            hex(id(self)),
            )


#
#   IPv4Network
#

@bacpypes_debugging
class IPv4Network(Network):

    """
    IPNetwork instances are Network objects where the addresses on the
    network are IPv4 socket tuples.
    """

    def __init__(self, address, name=''):
        if _debug: IPv4Network._debug("__init__ %r name=%r", address, name)
        Network.__init__(self, name=name)

        if isinstance(address, str):
            addr = IPv4Address(address)
        elif isinstance(address, IPv4Address):
            addr = address
        else:
            raise TypeError("address")

        # make sure this is just a network
        if int(addr) & int(addr.hostmask):
            raise ValueError("%s has host bits set" % (address,))

        # save the network for new nodes and broadcast address
        self.network = addr.network
        if _debug: IPv4Network._debug("    - network: %r", self.network)

        self.broadcast_address = addr.addrBroadcastTuple
        if _debug: IPv4Network._debug("    - broadcast_address: %r", self.broadcast_address)

    def add_node(self, node):
        if _debug: IPv4Network._debug("add_node %r", node)

        # convert the tuple to an address
        addr = IPv4Address(node.address)

        # first node sets the network and broadcast tuple, other nodes much match
        if not self.network:
            self.network = addr.network

        # make sure the node is in the network
        if addr.ip not in self.network:
            raise ValueError("node %s not on network %s" % (addr, self.network))

        # continue along
        Network.add_node(self, node)


#
#   IPv4Node
#

@bacpypes_debugging
class IPv4Node(Node):

    """
    An IPv4Node is a Node connected to an IPv4Network.
    """

    def __init__(self, addr, lan=None, promiscuous=False, spoofing=False, sid=None):
        if _debug: IPv4Node._debug("__init__ %r lan=%r", addr, lan)

        # make sure it's an Address that has appropriate pieces
        if isinstance(addr, str):
            addrTuple = IPv4Address(addr).addrTuple
        elif isinstance(addr, IPv4Address):
            addrTuple = addr.addrTuple
        elif isinstance(addr, tuple):
            addrTuple = addr
        else:
            raise TypeError("address")

        # continue initializing
        Node.__init__(self, addrTuple, lan=lan, promiscuous=promiscuous, spoofing=spoofing, sid=sid)


#
#   IPv4RouterNode
#

@bacpypes_debugging
class IPv4RouterNode(Client):

    """
    An instance of this class acts as an IPv4Node and forwards PDUs to the
    IPv4Router for processing.
    """

    def __init__(self, router, addr, lan):
        if _debug: IPv4RouterNode._debug("__init__ %r %r lan=%r", router, addr, lan)

        # save the references to the router for packets and the lan for debugging
        self.router = router
        self.lan = lan

        # make ourselves an IPNode and bind to it
        self.node = IPv4Node(addr, lan=lan, promiscuous=True, spoofing=True)
        bind(self, self.node)

    def confirmation(self, pdu):
        if _debug: IPv4RouterNode._debug("confirmation %r", pdu)

        self.router.process_pdu(self, pdu)

    def process_pdu(self, pdu):
        if _debug: IPv4RouterNode._debug("process_pdu %r", pdu)

        # pass it downstream
        self.request(pdu)

    def __repr__(self):
        return "<%s for %s>" % (self.__class__.__name__, self.lan.name)


#
#   IPv4Router
#

@bacpypes_debugging
class IPv4Router:

    def __init__(self):
        if _debug: IPv4Router._debug("__init__")

        # connected network nodes
        self.nodes = []

    def add_network(self, addr, lan):
        if _debug: IPv4Router._debug("add_network %r %r", addr, lan)

        node = IPv4RouterNode(self, addr, lan)
        if _debug: IPv4Router._debug("    - node: %r", node)

        self.nodes.append(node)

    def process_pdu(self, node, pdu):
        if _debug: IPv4Router._debug("process_pdu %r %r", node, pdu)

        # make an address out of the destination
        dest_address = IPv4Address(pdu.pduDestination[0])

        # loop through the other nodes
        for router_node in self.nodes:
            if router_node is node:
                continue
            if dest_address.ip in router_node.lan.network:
                if _debug: IPv4Router._debug("    - router_node: %r", router_node)
                router_node.process_pdu(pdu)

