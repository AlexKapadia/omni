"""Server assembly layer: the wiring between the WS surface and the engine.

Purpose: every module here either dispatches validated WebSocket commands to
a domain service (``*_command_dispatcher``) or assembles a domain feature
onto the running server (``*_server_wiring``, gateways, default service
factories). No domain logic lives here — only construction, routing, and
lifecycle glue.
Pipeline position: imported by ``engine.server`` and
``engine.websocket_connection_handler`` (which stay at the engine root as
the process entrypoints); everything below is the domain packages
(``audio``, ``stt``, ``enhance``, ``agents``, ``vault``, ...).

Security invariant: dispatchers validate payloads fail-closed (deny by
default) before any service call; wiring never widens a domain boundary.
"""
