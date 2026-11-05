"""Golden core: settings, logging, errors, middleware, security, data, outbound HTTP.

Extend, never rewrite. These modules are frozen against agent edits; feature code lives in
`app.features.<package>` and plugs in through `app.features.registry`.
"""
