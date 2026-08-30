"""
Broker integrations.

Two independent broker SDKs live as sibling sub-packages here — pick the one
you need explicitly, there is no broker-agnostic re-export at this level::

    from broker.schwab import Client
    from broker.tastytrade import TastytradeClient

See broker/schwab/__init__.py and broker/tastytrade/__init__.py for each
SDK's full usage.
"""
