#!/usr/bin/python

"""
PDU
"""

import re
import socket
import struct
import ipaddress

try:
    import netifaces
except ImportError:
    netifaces = None

from .debugging import ModuleLogger, bacpypes_debugging, btox, xtob
from .comm import PCI as _PCI, PDUData

# pack/unpack constants
_short_mask = 0xFFFFL
_long_mask = 0xFFFFFFFFL

# some debugging
_debug = 0
_log = ModuleLogger(globals())

# globals
network_types = None    # bottom of this module after class definitions

# parsing patterns
ipv4_net_addr_port_re = re.compile(r'^(?:(\d+):)?(\d+\.\d+\.\d+\.\d+(?:/\d+)?)(?::(\d+))?$')
ipv6_net_addr_port_re = re.compile(r'^(?:(\d+):)?(?:[[])([.:0-9A-Fa-f]+(?:/\d+)?)(?:[]])(?::(\d+))?$')
ethernet_re = re.compile(r'^([0-9A-Fa-f][0-9A-Fa-f][:]){5}([0-9A-Fa-f][0-9A-Fa-f])$' )
interface_port_re = re.compile(r'^(\w+)(?::(\d+))?$')

#
#   if_nametoindex
#

import ctypes
import ctypes.util

libc = ctypes.CDLL(ctypes.util.find_library('c'))

def if_nametoindex(name):
    if not isinstance(name, str):
        raise TypeError('name must be a string.')
    ret = libc.if_nametoindex(name)
    if not ret:
        raise RunTimeError("Invalid Name")
    return ret

#
#   AddressMetaclass
#

@bacpypes_debugging
class AddressMetaclass(type):

    def __new__(cls, clsname, superclasses, attributedict):
        if _debug: AddressMetaclass._debug("__new__ %r %r %r", clsname, superclasses, attributedict)

        return type.__new__(cls, clsname, superclasses, attributedict)

    def __call__(cls, *args, **kwargs):
        if _debug: AddressMetaclass._debug("__call__ %r %r %r", cls, args, kwargs)
        global network_types, network_type_order

        # already subclassed, nothing to see here
        if cls is not Address:
            return type.__call__(cls, *args, **kwargs)

        network_type = kwargs.get('network_type', None)

        # network type was provided
        if network_type:
            if network_type not in network_types:
                raise ValueError("invalid network type")

            return super(AddressMetaclass, network_types[network_type]).__call__(*args, **kwargs)

        if not args:
            if _debug: AddressMetaclass._debug("    - null")
            return super(AddressMetaclass, NullAddress).__call__(*args, **kwargs)

        # match the address
        addr = args[0]

        if isinstance(addr, (int, long)):
            if addr < 0:
                raise ValueError("invalid address")
            if addr <= 255:
                return super(AddressMetaclass, ARCNETAddress).__call__(addr, **kwargs)
            if addr <= _long_mask:
                return super(AddressMetaclass, IPv4Address).__call__(addr, **kwargs)

            # last chance
            return super(AddressMetaclass, IPv6Address).__call__(addr, **kwargs)

        if isinstance(addr, basestring):
            if addr == "*":
                if _debug: AddressMetaclass._debug("    - local broadcast")
                return super(AddressMetaclass, LocalBroadcast).__call__(**kwargs)

            if addr == "*:*":
                if _debug: AddressMetaclass._debug("    - global broadcast")
                return super(AddressMetaclass, GlobalBroadcast).__call__(**kwargs)

            if re.match(r"^\d+$", addr):
                if _debug: AddressMetaclass._debug("    - int")
                return super(AddressMetaclass, LocalStation).__call__(int(addr), **kwargs)

            if re.match(r"^\d+:[*]$", addr):
                if _debug: AddressMetaclass._debug("    - remote broadcast")

                net = int(args[0][:-2])
                if _debug: AddressMetaclass._debug("    - net: %r", net)

                return super(AddressMetaclass, RemoteBroadcast).__call__(net, **kwargs)

            if re.match(r"^\d+:\d+$", addr):
                if _debug: AddressMetaclass._debug("    - remote station")

                net, addr = addr.split(':')
                return super(AddressMetaclass, RemoteStation).__call__(int(net), int(addr), **kwargs)

            if re.match(r"^0x([0-9A-Fa-f][0-9A-Fa-f])+$",addr):
                if _debug: AddressMetaclass._debug("    - modern hex string")
                return super(AddressMetaclass, LocalStation).__call__(bytearray(xtob(addr[2:])), **kwargs)

            if re.match(r"^X'([0-9A-Fa-f][0-9A-Fa-f])+'$",addr):
                if _debug: AddressMetaclass._debug("    - old school hex string")
                return super(AddressMetaclass, LocalStation).__call__(bytearray(xtob(addr[2:-1])), **kwargs)

            if re.match(r"^\d+:0x([0-9A-Fa-f][0-9A-Fa-f])+$",addr):
                if _debug: AddressMetaclass._debug("    - remote station with modern hex string")

                net, addr = addr.split(':')
                return super(AddressMetaclass, RemoteStation).__call__(int(net), bytearray(xtob(addr[2:])), **kwargs)

            if re.match(r"^\d+:X'([0-9A-Fa-f][0-9A-Fa-f])+'$",addr):
                if _debug: AddressMetaclass._debug("    - remote station with old school hex string")

                net, addr = addr.split(':')
                return super(AddressMetaclass, RemoteStation).__call__(int(net), bytearray(xtob(addr[2:-1])), **kwargs)

            if ipv4_net_addr_port_re.match(addr):
                return super(AddressMetaclass, IPv4Address).__call__(*args, **kwargs)

            if ipv6_net_addr_port_re.match(addr):
                return super(AddressMetaclass, IPv6Address).__call__(*args, **kwargs)

            if ethernet_re.match(addr):
                return super(AddressMetaclass, EthernetAddress).__call__(*args, **kwargs)

            if interface_port_re.match(addr):
                return super(AddressMetaclass, IPv4Address).__call__(*args, **kwargs)

        if isinstance(addr, (bytes, bytearray)):
            if _debug: AddressMetaclass._debug("    - bytes or bytearray")
            addr = bytearray(addr)

            if len(addr) <= 0:
                raise ValueError("invalid address")

            if len(addr) == 1:
                return super(AddressMetaclass, ARCNETAddress).__call__(addr, **kwargs)
            if len(addr) == 6:
                return super(AddressMetaclass, IPv4Address).__call__(addr, **kwargs)
            if len(addr) == 18:
                return super(AddressMetaclass, IPv6Address).__call__(addr, **kwargs)

        if isinstance(addr, tuple):
            if _debug: AddressMetaclass._debug("    - tuple")
            addr, port = addr
            if isinstance(addr, basestring):
                addr = unicode(addr)

            try:
                test_address = ipaddress.ip_address(addr)
                if _debug: AddressMetaclass._debug("    - test_address: %r", test_address)

                if isinstance(test_address, ipaddress.IPv4Address):
                    if _debug: AddressMetaclass._debug("    - ipv4")
                    return super(AddressMetaclass, IPv4Address).__call__(addr, port=port, **kwargs)
                elif isinstance(test_address, ipaddress.IPv6Address):
                    if _debug: AddressMetaclass._debug("    - ipv6")
                    return super(AddressMetaclass, IPv6Address).__call__(addr, port=port, **kwargs)
            except Exception as err:
                if _debug: AddressMetaclass._debug("    - err: %r", err)

        raise ValueError("invalid address")

#
#   Address
#

@bacpypes_debugging
class Address:
    __metaclass__ = AddressMetaclass

    nullAddr = 0
    localBroadcastAddr = 1
    localStationAddr = 2
    remoteBroadcastAddr = 3
    remoteStationAddr = 4
    globalBroadcastAddr = 5

    def __init__(self, *args, **kwargs):
        if _debug: Address._debug("__init__ %r %r", args, kwargs)
        raise NotImplementedError

    @classmethod
    def is_valid(cls, *args):
        """Return True if arg is valid value for the class."""
        raise NotImplementedError

    def __repr__(self):
        return "<%s %s>" % (self.__class__.__name__, self.__str__())

    def __str__(self):
        return '?'

    def __hash__(self):
        return hash( (self.addrType, self.addrNet, self.addrAddr) )

    def __eq__(self, arg):
        # try an coerce it into an address
        if not isinstance(arg, Address):
            arg = Address(arg)

        # all of the components must match
        return (self.addrType == arg.addrType) and (self.addrNet == arg.addrNet) and (self.addrAddr == arg.addrAddr)

    def __ne__(self,arg):
        return not self.__eq__(arg)

#
#   NullAddress
#

@bacpypes_debugging
class NullAddress(Address):

    def __init__(self, network_type='null'):
        if _debug: NullAddress._debug("NullAddress.__init__ network_type=%r", network_type)

        if network_type != 'null':
            raise ValueError("network type must be 'null'")

        self.addrType = Address.nullAddr
        self.addrNet = None
        self.addrLen = 0
        self.addrAddr = b''

    @classmethod
    def is_valid(cls, *args):
        """No arguments for a null address."""
        return bool(not args)

    def __str__(self):
        return 'Null'

#
#   LocalStation
#

@bacpypes_debugging
class LocalStation(Address):

    def __init__(self, addr, network_type=None):
        if _debug: LocalStation._debug("__init__ %r network_type=%r", addr, network_type)

        if network_type and network_type not in network_types:
            raise ValueError("invalid network type")

        self.addrType = Address.localStationAddr
        self.addrNetworkType = network_type
        self.addrNet = None

        if isinstance(addr, (int, long)):
            if (addr < 0) or (addr >= 256):
                raise ValueError("address out of range")

            self.addrAddr = struct.pack('B', addr)
            self.addrLen = 1

        elif isinstance(addr, (bytes, bytearray)):
            if _debug: Address._debug("    - bytes or bytearray")

            self.addrAddr = bytes(addr)
            self.addrLen = len(addr)

        else:
            raise TypeError("integer, bytes or bytearray required")

    def __str__(self):
        if self.addrLen == 1:
            addrstr = str(ord(self.addrAddr))
        elif self.addrLen == 6:
            port = struct.unpack('>H', self.addrAddr[-2:])[0]
            if (47808 <= port <= 47810):
                addrstr = socket.inet_ntoa(self.addrAddr[:4])
                if port != 47808:
                    addrstr += ':' + str(port)
            else:
                addrstr = '0x' + btox(self.addrAddr)
        else:
            addrstr = '0x' + btox(self.addrAddr)
        return addrstr

#
#   LocalBroadcast
#

@bacpypes_debugging
class LocalBroadcast(Address):

    def __init__(self, network_type=None):
        if _debug: LocalBroadcast._debug("__init__ network_type=%r", network_type)

        if network_type and network_type not in network_types:
            raise ValueError("invalid network type")

        self.addrType = Address.localBroadcastAddr
        self.addrNetworkType = network_type
        self.addrNet = None
        self.addrAddr = None
        self.addrLen = None

    def __str__(self):
        if _debug: LocalBroadcast._debug("__str__")
        return "*"

#
#   RemoteStation
#

class RemoteStation(Address):

    def __init__(self, net, addr, network_type=None):
        if not isinstance(net, (int, long)):
            raise TypeError("integer network required")
        if (net < 0) or (net >= 65535):
            raise ValueError("network out of range")

        if network_type and network_type not in network_types:
            raise ValueError("invalid network type")

        self.addrType = Address.remoteStationAddr
        self.addrNetworkType = network_type
        self.addrNet = net

        if isinstance(addr, (int, long)):
            if (addr < 0) or (addr >= 256):
                raise ValueError("address out of range")

            self.addrAddr = struct.pack('B', addr)
            self.addrLen = 1

        elif isinstance(addr, (bytes, bytearray)):
            if _debug: Address._debug("    - bytes or bytearray")

            self.addrAddr = bytes(addr)
            self.addrLen = len(addr)

        else:
            raise TypeError("integer, bytes or bytearray required")

    def __str__(self):
        prefix = str(self.addrNet) + ':'
        if self.addrLen == 1:
            addrstr = str(ord(self.addrAddr))
        elif self.addrLen == 6:
            port = struct.unpack('>H', self.addrAddr[-2:])[0]
            if (47808 <= port <= 47810):
                addrstr = socket.inet_ntoa(self.addrAddr[:4])
                if port != 47808:
                    addrstr += ':' + str(port)
            else:
                addrstr = '0x' + btox(self.addrAddr)
        else:
            addrstr = '0x' + btox(self.addrAddr)
        return prefix + addrstr

#
#   RemoteBroadcast
#

class RemoteBroadcast(Address):

    def __init__(self, net, network_type=None):
        if not isinstance(net, (int, long)):
            raise TypeError("integer network required")
        if (net < 0) or (net >= 65535):
            raise ValueError("network out of range")

        if network_type and network_type not in network_types:
            raise ValueError("invalid network type")

        self.addrType = Address.remoteBroadcastAddr
        self.addrNetworkType = network_type

        self.addrNet = net
        self.addrAddr = None
        self.addrLen = None

    def __str__(self):
        return str(self.addrNet) + ':*'

#
#   GlobalBroadcast
#

class GlobalBroadcast(Address):

    def __init__(self):
        self.addrType = Address.globalBroadcastAddr
        self.addrNet = None
        self.addrAddr = None
        self.addrLen = None

    def __str__(self):
        return '*:*'

#
#   EthernetAddress
#

@bacpypes_debugging
class EthernetAddress(Address):

    def __init__(self, addr, network_type='ethernet'):
        if _debug: EthernetAddress._debug("__init__ %r network_type=%r", addr, network_type)

        if network_type != 'ethernet':
            raise ValueError("network type must be 'ethernet'")

        self.addrType = Address.localStationAddr
        self.addrNetworkType = 'ethernet'
        self.addrNet = None

        if isinstance(addr, basestring) and ethernet_re.match(addr):
            self.addrAddr = xtob(addr, ':')
        elif isinstance(addr, (bytes, bytearray)):
            self.addrAddr = bytes(addr)

        self.addrLen = 6

    def __str__(self):
        suffix = ", net " + str(self.addrNet) if self.addrNet else ''
        return btox(self.addrAddr, sep=':') + suffix

#
#   EthernetBroadcastAddress
#

@bacpypes_debugging
class EthernetBroadcastAddress(LocalBroadcast, EthernetAddress):

    def __init__(self):
        if _debug: EthernetAddress._debug("__init__")
        EthernetAddress.__init__(self, '\xFF' * 6)

        # override the address type
        self.addrType = Address.localBroadcastAddr

#
#   ARCNETAddress
#

@bacpypes_debugging
class ARCNETAddress(Address):

    def __init__(self, addr, network_type='arcnet'):
        if _debug: ARCNETAddress._debug("__init__ %r network_type=%r", addr, network_type)

        if network_type != 'arcnet':
            raise ValueError("network type must be 'arcnet'")

        self.addrType = Address.localStationAddr
        self.addrNetworkType = 'arcnet'
        self.addrNet = None

        if _debug: ARCNETAddress._debug("    - %r", type(addr))

        if isinstance(addr, (int, long)):
            if _debug: ARCNETAddress._debug("    - int")
            self.addrAddr = struct.pack('B', addr)

        elif isinstance(addr, basestring):
            if _debug: ARCNETAddress._debug("    - str")
            self.addrAddr = struct.pack('B', ord(addr))

        elif isinstance(addr, (bytes, bytearray)):
            if _debug: ARCNETAddress._debug("    - bytes, bytearray")
            self.addrAddr = bytes(addr)

        else:
            raise ValueError("invalid address")

        self.addrLen = 1

    def __str__(self):
        prefix = str(self.addrNet) + ':' if self.addrNet else ''
        return prefix + str(ord(self.addrAddr))

#
#   MSTPAddress
#

@bacpypes_debugging
class MSTPAddress(Address):

    def __init__(self, addr, network_type='mstp'):
        if _debug: MSTPAddress._debug("__init__ %r network_type=%r", addr, network_type)

        if network_type != 'mstp':
            raise ValueError("network type must be 'mstp'")

        self.addrType = Address.localStationAddr
        self.addrNetworkType = 'arcnet'
        self.addrNet = None

        if isinstance(addr, (int, long)):
            self.addrAddr = struct.pack('B', addr)

        elif isinstance(addr, (bytes, bytearray)):
            self.addrAddr = bytes(addr)

        elif isinstance(addr, basestring):
            self.addrAddr = struct.pack('B', int(addr))

        self.addrLen = 1

    def __str__(self):
        prefix = str(self.addrNet) + ':' if self.addrNet else ''
        return prefix + str(ord(self.addrAddr))

#
#   IPv4Address
#

@bacpypes_debugging
class IPv4Address(Address, ipaddress.IPv4Interface):

    def __init__(self, addr, port=47808, network_type='ipv4'):
        if _debug: IPv4Address._debug("__init__ %r network_type=%r", addr, network_type)
        if _debug: IPv4Address._debug("    - type(addr): %r", type(addr))

        if network_type != 'ipv4':
            raise ValueError("network type must be 'ipv4'")

        self.addrType = Address.localStationAddr
        self.addrNetworkType = 'ipv4'
        self.addrNet = None

        # if this is a remote station, suck out the network
        if isinstance(addr, RemoteStation):
            self.addrType = Address.remoteStationAddr
            self.addrNet = addr.addrNet

        # if this is some other kind of address, suck out the guts
        if isinstance(addr, Address):
            addr = bytearray(addr.addrAddr)
            if len(addr) != 6:
                raise ValueError("invalid address length")

        if isinstance(addr, (int, long)):
            if _debug: IPv4Address._debug("    - int")
            ipaddress.IPv4Interface.__init__(self, addr)

        elif isinstance(addr, basestring):
            if _debug: IPv4Address._debug("    - str")

            while True:
                ipv4_match = ipv4_net_addr_port_re.match(addr)
                if ipv4_match:
                    _net, addr, _port = ipv4_match.groups()
                    if _debug: IPv4Address._debug("    - _net, addr, _port: %r, %r, %r", _net, addr, _port)

                    if _net:
                        self.addrType = Address.remoteStationAddr
                        self.addrNet = int(_net)

                    ipaddress.IPv4Interface.__init__(self, unicode(addr))

                    if _port:
                        port = int(_port)
                    break

                interface_port_match = interface_port_re.match(addr)
                if interface_port_match:
                    if not netifaces:
                        raise RuntimeError("install netifaces for interface name addresses")

                    interface, _port = interface_port_match.groups()
                    if _debug: IPv4Address._debug("    - interface, _port: %r, %r", interface, _port)

                    ifaddresses = netifaces.ifaddresses(interface)
                    ipv4_addresses = ifaddresses.get(netifaces.AF_INET, None)
                    if not ipv4_addresses:
                        ValueError("no IPv4 address for interface: %r" % (interface,))
                    if len(ipv4_addresses) > 1:
                        ValueError("multiple IPv4 addresses for interface: %r" % (interface,))

                    ipv4_address = ipv4_addresses[0]
                    if _debug: IPv4Address._debug("    - ipv4_address: %r", ipv4_address)

                    ipaddress.IPv4Interface.__init__(self, unicode(ipv4_address['addr'] + '/' + ipv4_address['netmask']))

                    if _port:
                        port = int(_port)
                    break

                # last chance, assume bytes
                if len(addr) == 6:
                    ipaddress.IPv4Interface.__init__(self, bytes(addr[:4]))

                    # extract the port
                    port = struct.unpack('!H', addr[4:6])[0]
                    break

                raise ValueError("invalid address")

        elif isinstance(addr, (bytes, bytearray)):
            if _debug: IPv4Address._debug("    - bytes: %r..%r", addr[:4], addr[4:6])
            ipaddress.IPv4Interface.__init__(self, bytes(addr[:4]))

            # extract the port
            port = struct.unpack('!H', addr[4:6])[0]

        elif isinstance(addr, tuple):
            if _debug: IPv4Address._debug("    - tuple")
            addr, port = addr

            if isinstance(addr, (int, long)):
                ipaddress.IPv4Interface.__init__(self, addr)
            elif isinstance(addr, basestring):
                ipaddress.IPv4Interface.__init__(self, unicode(addr))

        else:
            raise ValueError("invalid address")

        self.addrAddr = self.packed + struct.pack('!H', port & _short_mask)
        self.addrLen = 6

        self.addrPort = port
        self.addrTuple = (self.ip.compressed, port)
        self.addrBroadcastTuple = (self.network.broadcast_address.compressed, port)

    def __str__(self):
        prefix = str(self.addrNet) + ':' if self.addrNet else ''
        suffix = ':' + str(self.addrPort) if (self.addrPort != 47808) else ''

        return prefix + self.ip.compressed + suffix

#
#   IPv6Address
#

@bacpypes_debugging
class IPv6Address(Address, ipaddress.IPv6Interface):

    def __init__(self, addr, port=47808, interface=None, network_type='ipv6'):
        if _debug: IPv6Address._debug("__init__ %r network_type=%r", addr, network_type)

        if network_type != 'ipv6':
            raise ValueError("network type must be 'ipv6'")

        self.addrType = Address.localStationAddr
        self.addrNetworkType = 'ipv6'
        self.addrNet = None

        # if this is a remote station, suck out the network
        if isinstance(addr, RemoteStation):
            self.addrType = Address.remoteStationAddr
            self.addrNet = addr.addrNet

        # if this is some other kind of address, suck out the guts
        if isinstance(addr, Address):
            addr = bytearray(addr.addrAddr)
            if len(addr) != 18:
                raise ValueError("invalid address length")

        if interface is None:
            interface_index = 0
        elif isinstance(interface, (int, long)):
            interface_index = interface
        elif isinstance(interface, basestring):
            interface_index = if_nametoindex(interface)
        else:
            raise ValueError("invalid interface")
        if _debug: IPv6Address._debug("    - interface_index: %r", interface_index)

        if isinstance(addr, (int, long)):
            if _debug: IPv6Address._debug("    - int")
            ipaddress.IPv6Interface.__init__(self, addr)

        elif isinstance(addr, basestring):
            if _debug: IPv6Address._debug("    - str")

            while True:
                ipv6_match = ipv6_net_addr_port_re.match(addr)
                if ipv6_match:
                    _net, addr, _port = ipv6_match.groups()
                    if _debug: IPv6Address._debug("    - _net, addr, _port: %r, %r, %r", _net, addr, _port)

                    if _net:
                        self.addrType = Address.remoteStationAddr
                        self.addrNet = int(_net)

                    ipaddress.IPv6Interface.__init__(self, unicode(addr))

                    if _port:
                        port = int(_port)
                    break

                interface_port_match = interface_port_re.match(addr)
                if interface_port_match:
                    if not netifaces:
                        raise RuntimeError("install netifaces for interface name addresses")

                    _interface, _port = interface_port_match.groups()
                    if _debug: IPv6Address._debug("    - _interface, _port: %r, %r", _interface, _port)

                    if (_interface and interface is not None) and (_interface != interface):
                        raise ValueError("interface mismatch")
                        interface = _interface

                    if _port:
                        port = int(_port)

                    ifaddresses = netifaces.ifaddresses(_interface)
                    ipv6_addresses = ifaddresses.get(netifaces.AF_INET6, None)
                    if not ipv6_addresses:
                        ValueError("no IPv6 address for interface: %r" % (interface,))
                    if len(ipv6_addresses) > 1:
                        ValueError("multiple IPv6 addresses for interface: %r" % (interface,))

                    ipv6_address = ipv6_addresses[0]
                    if _debug: IPv6Address._debug("    - ipv6_address: %r", ipv6_address)

                    # get the address
                    addr = ipv6_address['addr']
                    if _debug: IPv6Address._debug("    - addr: %r", addr)

                    # find the interface name
                    if '%' in addr:
                        addr, _interface = addr.split('%')
                        if (interface is not None) and (_interface != interface):
                            raise ValueError("interface mismatch")

                    interface_index = if_nametoindex(str(_interface))
                    if _debug: IPv6Address._debug("    - interface_index: %r", interface_index)

                    # get the netmask and pull the size off the end
                    netmask = ipv6_address['netmask']
                    netmask = netmask[netmask.rfind('/'):]
                    if _debug: IPv6Address._debug("    - netmask: %r", netmask)

                    ipaddress.IPv6Interface.__init__(self, unicode(addr + netmask))
                    break

                # raw, perhaps compressed, address
                if re.match("^[.:0-9A-Fa-f]+$", addr):
                    if _debug: IPv6Address._debug("    - just an address")
                    ipaddress.IPv6Interface.__init__(self, unicode(addr))
                    break

                # last chance, assume bytes
                if len(addr) == 18:
                    if _debug: IPv6Address._debug("    - assuming bytes")
                    ipaddress.IPv6Interface.__init__(self, bytes(addr[:16]))

                    # extract the port
                    port = struct.unpack('!H', addr[16:18])[0]
                    break

                raise ValueError("invalid address")

        elif isinstance(addr, (bytes, bytearray)):
            if _debug: IPv6Address._debug("    - bytes")

            ipaddress.IPv6Interface.__init__(self, bytes(addr[:16]))

            # extract the port
            port = struct.unpack('!H', addr[16:18])[0]

        elif isinstance(addr, tuple):
            if _debug: IPv6Address._debug("    - tuple")
            addr, port = addr

            if isinstance(addr, (int, long)):
                ipaddress.IPv6Interface.__init__(self, addr)
            elif isinstance(addr, basestring):
                ipaddress.IPv6Interface.__init__(self, uniicode(addr))

        self.addrAddr = self.packed + struct.pack('!H', port & _short_mask)
        self.addrLen = 6

        self.addrPort = port
        self.addrTuple = (self.ip.compressed, port, 0, interface_index)

    def __str__(self):
        prefix = str(self.addrNet) + ':[' if self.addrNet else '['
        suffix = ']:' + str(self.addrPort) if (self.addrPort != 47808) else ']'

        return prefix + self.ip.compressed + suffix

#
#   IPv6MulticastAddress
#

@bacpypes_debugging
class IPv6MulticastAddress(LocalBroadcast, ipaddress.IPv6Address):

    def __init__(self, addr, port=47808, interface=None):
        if _debug: IPv6MulticastAddress._debug("__init__ %r", addr)

        LocalBroadcast.__init__(self, 'ipv6')

        if isinstance(addr, basestring) and re.match("^[.:0-9A-Fa-f]+$", addr):
            if _debug: IPv6MulticastAddress._debug("    - str")
            ipaddress.IPv6Address.__init__(self, unicode(addr))
        else:
            raise ValueError("invalid address")

        # a little error checking
        if not self.is_multicast:
            raise ValueError("not a multicast address: %r" % (addr,))

        if interface is None:
            interface_index = 0
        elif isinstance(interface, (int, long)):
            interface_index = interface
        elif isinstance(interface, basestring):
            interface_index = if_nametoindex(str(interface))
        else:
            raise ValueError("invalid interface")
        if _debug: IPv6MulticastAddress._debug("    - interface_index: %r", interface_index)

        self.addrPort = port
        self.addrTuple = (self.compressed, port, 0, interface_index)

    def __str__(self):
        if _debug: IPv6MulticastAddress._debug("__str__")
        return ipaddress.IPv6Address.__str__(self)

#
#   IPv6InterfaceLocalMulticastAddress
#

@bacpypes_debugging
class IPv6InterfaceLocalMulticastAddress(IPv6MulticastAddress):

    def __init__(self, port=47808, interface=None):
        if _debug: IPv6InterfaceLocalMulticastAddress._debug("__init__")
        IPv6MulticastAddress.__init__(self, "ff01::bac0", port=port, interface=interface)

#
#   IPv6LinkLocalMulticastAddress
#

@bacpypes_debugging
class IPv6LinkLocalMulticastAddress(IPv6MulticastAddress):

    def __init__(self, port=47808, interface=None):
        if _debug: IPv6LinkLocalMulticastAddress._debug("__init__")
        IPv6MulticastAddress.__init__(self, "ff02::bac0", port=port, interface=interface)

#
#   IPv6AdminLocalMulticastAddress
#

@bacpypes_debugging
class IPv6AdminLocalMulticastAddress(IPv6MulticastAddress):

    def __init__(self, port=47808, interface=None):
        if _debug: IPv6AdminLocalMulticastAddress._debug("__init__")
        IPv6MulticastAddress.__init__(self, "ff04::bac0", port=port, interface=interface)

#
#   IPv6SiteLocalMulticastAddress
#

@bacpypes_debugging
class IPv6SiteLocalMulticastAddress(IPv6MulticastAddress):

    def __init__(self, port=47808, interface=None):
        if _debug: IPv6SiteLocalMulticastAddress._debug("__init__")
        IPv6MulticastAddress.__init__(self, "ff05::bac0", port=port, interface=interface)

#
#   IPv6OrganizationLocalMulticastAddress
#

@bacpypes_debugging
class IPv6OrganizationLocalMulticastAddress(IPv6MulticastAddress):

    def __init__(self, port=47808, interface=None):
        if _debug: IPv6OrganizationLocalMulticastAddress._debug("__init__")
        IPv6MulticastAddress.__init__(self, "ff08::bac0", port=port, interface=interface)

#
#   IPv6GlobalMulticastAddress
#

@bacpypes_debugging
class IPv6GlobalMulticastAddress(IPv6MulticastAddress):

    def __init__(self, port=47808, interface=None):
        if _debug: IPv6GlobalMulticastAddress._debug("__init__")
        IPv6MulticastAddress.__init__(self, "ff0e::bac0", port=port, interface=interface)

#
#   PCI
#

@bacpypes_debugging
class PCI(_PCI):

    _debug_contents = ('pduExpectingReply', 'pduNetworkPriority')

    def __init__(self, *args, **kwargs):
        if _debug: PCI._debug("__init__ %r %r", args, kwargs)

        # split out the keyword arguments that belong to this class
        my_kwargs = {}
        other_kwargs = {}
        for element in ('expectingReply', 'networkPriority'):
            if element in kwargs:
                my_kwargs[element] = kwargs[element]
        for kw in kwargs:
            if kw not in my_kwargs:
                other_kwargs[kw] = kwargs[kw]
        if _debug: PCI._debug("    - my_kwargs: %r", my_kwargs)
        if _debug: PCI._debug("    - other_kwargs: %r", other_kwargs)

        # call some superclass, if there is one
        super(PCI, self).__init__(*args, **other_kwargs)

        # set the attribute/property values for the ones provided
        self.pduExpectingReply = my_kwargs.get('expectingReply', 0)     # see 6.2.2 (1 or 0)
        self.pduNetworkPriority = my_kwargs.get('networkPriority', 0)   # see 6.2.2 (0..3)

    def update(self, pci):
        """Copy the PCI fields."""
        _PCI.update(self, pci)

        # now do the BACnet PCI fields
        self.pduExpectingReply = pci.pduExpectingReply
        self.pduNetworkPriority = pci.pduNetworkPriority

    def pci_contents(self, use_dict=None, as_class=dict):
        """Return the contents of an object as a dict."""
        if _debug: PCI._debug("pci_contents use_dict=%r as_class=%r", use_dict, as_class)

        # make/extend the dictionary of content
        if use_dict is None:
            use_dict = as_class()

        # call the parent class
        _PCI.pci_contents(self, use_dict=use_dict, as_class=as_class)

        # save the values
        use_dict.__setitem__('expectingReply', self.pduExpectingReply)
        use_dict.__setitem__('networkPriority', self.pduNetworkPriority)

        # return what we built/updated
        return use_dict

    def dict_contents(self, use_dict=None, as_class=dict):
        """Return the contents of an object as a dict."""
        if _debug: PCI._debug("dict_contents use_dict=%r as_class=%r", use_dict, as_class)

        return self.pci_contents(use_dict=use_dict, as_class=as_class)

#
#   PDU
#

@bacpypes_debugging
class PDU(PCI, PDUData):

    def __init__(self, *args, **kwargs):
        if _debug: PDU._debug("__init__ %r %r", args, kwargs)
        super(PDU, self).__init__(*args, **kwargs)

    def __str__(self):
        return '<%s %s -> %s : %s>' % (self.__class__.__name__, self.pduSource, self.pduDestination, btox(self.pduData,'.'))

    def dict_contents(self, use_dict=None, as_class=dict):
        """Return the contents of an object as a dict."""
        if _debug: PDUData._debug("dict_contents use_dict=%r as_class=%r", use_dict, as_class)

        # make/extend the dictionary of content
        if use_dict is None:
            use_dict = as_class()

        # call into the two base classes
        self.pci_contents(use_dict=use_dict, as_class=as_class)
        self.pdudata_contents(use_dict=use_dict, as_class=as_class)

        # return what we built/updated
        return use_dict

# network types
network_types = {
    'null': NullAddress,            # not a standard type
    'ethernet': EthernetAddress,
    'arcnet': ARCNETAddress,
    'mstp': MSTPAddress,
#   'ptp': PTPAddress,
#   'lontalk': LonTalkAddress,
    'ipv4': IPv4Address,
#   'zigbee': ZigbeeAddress,
#   'virtual': VirtualAddres,
    'ipv6': IPv6Address,
#   'serial': SerialAddress,
#   'secureConnect': SecureConnectAddress,
#   'websocket': WebSocketAddress,
    }

