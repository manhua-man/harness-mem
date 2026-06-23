"""harness_mem.integration — IDE hook installers for the v2.4.1 host entry.

v2.4.3 ships the maintenance surface that generates Cursor / Claude Code hook
scripts. Generated hooks invoke ``python -m harness_mem.host_entry`` and never
the ``harness-mem`` console script (v2.4.0 Req 10.2 boundary). See
:mod:`harness_mem.integration.installer`.
"""
