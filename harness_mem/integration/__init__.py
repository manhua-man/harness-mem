"""harness_mem.integration — host adapter installers for the host entry.

The integration surface now covers multiple host families: shell hooks, JSON
manifests, helper wrapper scripts, and plugin source files. Generated artifacts
invoke ``python -m harness_mem.host_entry`` and never the ``harness-mem``
console script (v2.4.0 Req 10.2 boundary). See
:mod:`harness_mem.integration.installer`.
"""
