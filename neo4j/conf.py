#!/usr/bin/env python
# -*- encoding: utf-8 -*-

# Copyright (c) 2002-2020 "Neo4j,"
# Neo4j Sweden AB [http://neo4j.com]
#
# This file is part of Neo4j.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from abc import ABCMeta
from collections.abc import Mapping
from warnings import warn

from neo4j.meta import get_user_agent

TRUST_SYSTEM_CA_SIGNED_CERTIFICATES = "TRUST_SYSTEM_CA_SIGNED_CERTIFICATES"  # Default
TRUST_ALL_CERTIFICATES = "TRUST_ALL_CERTIFICATES"


def iter_items(iterable):
    """ Iterate through all items (key-value pairs) within an iterable
    dictionary-like object. If the object has a `keys` method, this is
    used along with `__getitem__` to yield each pair in turn. If no
    `keys` method exists, each iterable element is assumed to be a
    2-tuple of key and value.
    """
    if hasattr(iterable, "keys"):
        for key in iterable.keys():
            yield key, iterable[key]
    else:
        for key, value in iterable:
            yield key, value


class DeprecatedAlias:

    def __init__(self, new):
        self.new = new


class ConfigType(ABCMeta):

    def __new__(mcs, name, bases, attributes):
        fields = []
        deprecated_aliases = {}

        for base in bases:
            if type(base) is mcs:
                fields += base.keys()
                deprecated_aliases.update(base._deprecated_aliases())

        for k, v in attributes.items():
            if isinstance(v, DeprecatedAlias):
                deprecated_aliases[k] = v.new
            elif not k.startswith("_") and not callable(v):
                fields.append(k)

        def keys(_):
            return fields

        def _deprecated_aliases(_):
            return deprecated_aliases

        def _deprecated_keys(_):
            return list(deprecated_aliases)

        def _get_new(_, key):
            return deprecated_aliases.get(key)

        attributes.setdefault("keys", classmethod(keys))
        attributes.setdefault("_deprecated_aliases", classmethod(_deprecated_aliases))
        attributes.setdefault("_deprecated_keys", classmethod(_deprecated_keys))
        attributes.setdefault("_get_new", classmethod(_get_new))

        return super(ConfigType, mcs).__new__(mcs, name, bases,
                                              {k: v for k, v in attributes.items()
                                               if k not in deprecated_aliases})


class Config(Mapping, metaclass=ConfigType):
    """ Base class for all configuration containers.
    """

    @staticmethod
    def consume_chain(data, *config_classes):
        values = []
        for config_class in config_classes:
            if not issubclass(config_class, Config):
                raise TypeError("%r is not a Config subclass" % config_class)
            values.append(config_class._consume(data))
        if data:
            raise ValueError("Unexpected config keys: %s" % ", ".join(data.keys()))
        return values

    @classmethod
    def consume(cls, data):
        config, = cls.consume_chain(data, cls)
        return config

    @classmethod
    def _consume(cls, data):
        config = {}
        if data:
            for key in list(cls.keys()) + list(cls._deprecated_keys()):
                try:
                    value = data.pop(key)
                except KeyError:
                    pass
                else:
                    config[key] = value
        return cls(config)

    def __update(self, data):
        data_dict = dict(iter_items(data))

        def set_attr(k, v):
            if k in self.keys():
                setattr(self, k, v)
            elif k in self._deprecated_keys():
                k0 = self._get_new(k)
                if k0 in data_dict:
                    raise ValueError("Cannot specify both '{}' and '{}' in config".format(k0, k))
                warn("The '{}' config key is deprecated, please use '{}' instead".format(k, k0))
                set_attr(k0, v)
            else:
                raise AttributeError(k)

        for key, value in data_dict.items():
            if value is not None:
                set_attr(key, value)

    def __init__(self, *args, **kwargs):
        for arg in args:
            self.__update(arg)
        self.__update(kwargs)

    def __repr__(self):
        attrs = []
        for key in self:
            attrs.append(" %s=%r" % (key, getattr(self, key)))
        return "<%s%s>" % (self.__class__.__name__, "".join(attrs))

    def __len__(self):
        return len(self.keys())

    def __getitem__(self, key):
        return getattr(self, key)

    def __iter__(self):
        return iter(self.keys())


class PoolConfig(Config):
    """ Connection pool configuration.
    """

    #:
    connect_timeout = 30.0  # seconds

    #:
    init_size = 1

    #:
    keep_alive = True

    #:
    max_age = 3600  # 1h
    max_connection_lifetime = DeprecatedAlias("max_age")

    #: Maximum number of connections per host
    max_size = 100
    max_connection_pool_size = DeprecatedAlias("max_size")

    #:
    protocol_version = None

    #:
    resolver = None

    #:
    encrypted = False

    #:
    user_agent = get_user_agent()

    #:
    trust = TRUST_SYSTEM_CA_SIGNED_CERTIFICATES

    def get_ssl_context(self):
        if not self.encrypted:
            return None

        import ssl

        ssl_context = None

        # SSL stands for Secure Sockets Layer and was originally created by Netscape.
        # SSLv2 and SSLv3 are the 2 versions of this protocol (SSLv1 was never publicly released).
        # After SSLv3, SSL was renamed to TLS.
        # TLS stands for Transport Layer Security and started with TLSv1.0 which is an upgraded version of SSLv3.

        # SSLv2 - (Disabled)
        # SSLv3 - (Disabled)
        # TLS 1.0 - Released in 1999, published as RFC 2246. (Disabled)
        # TLS 1.1 - Released in 2006, published as RFC 4346. (Disabled)
        # TLS 1.2 - Released in 2008, published as RFC 5246.

        try:
            # python 3.6+
            # https://docs.python.org/3.6/library/ssl.html#ssl.PROTOCOL_TLS_CLIENT
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

            # For recommended security options see
            # https://docs.python.org/3.6/library/ssl.html#protocol-versions
            ssl_context.options |= ssl.OP_NO_TLSv1      # Python 3.2
            ssl_context.options |= ssl.OP_NO_TLSv1_1    # Python 3.4

        except AttributeError:
            # python 3.5
            # https://docs.python.org/3.5/library/ssl.html#ssl.PROTOCOL_TLS
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)

            # For recommended security options see
            # https://docs.python.org/3.5/library/ssl.html#protocol-versions
            ssl_context.options |= ssl.OP_NO_SSLv2      # Python 3.2
            ssl_context.options |= ssl.OP_NO_SSLv3      # Python 3.2
            ssl_context.options |= ssl.OP_NO_TLSv1      # Python 3.2
            ssl_context.options |= ssl.OP_NO_TLSv1_1    # Python 3.4

            ssl_context.verify_mode = ssl.CERT_REQUIRED     # https://docs.python.org/3.5/library/ssl.html#ssl.SSLContext.verify_mode
            ssl_context.check_hostname = True               # https://docs.python.org/3.5/library/ssl.html#ssl.SSLContext.check_hostname

        if self.trust == TRUST_ALL_CERTIFICATES:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE     # https://docs.python.org/3.5/library/ssl.html#ssl.CERT_NONE

        ssl_context.set_default_verify_paths()  # https://docs.python.org/3.5/library/ssl.html#ssl.SSLContext.set_default_verify_paths
        return ssl_context
