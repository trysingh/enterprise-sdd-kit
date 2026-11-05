"""Reference slice (exemplar). A complete, tested feature in the shape every feature package uses.

Copy the shape, never the names: feature code must not import from this package, and feature tests
must not bind its feature file or reuse its @SCN-000-* ids (`RED-NO-EXEMPLAR`). It is mounted only
outside production (`APP_REFERENCE_SLICE_ENABLED`, and never when APP_ENV=prod).
"""
