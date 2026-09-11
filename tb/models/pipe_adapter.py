"""
Alias module.

The agent brief names this file `pipe_adapter.py`, from the era when
`CLAUDE.md` placed the chip boundary at PIPE.  DEC-002 removed PIPE from the
project entirely (cocotbext-pcie 0.2.16 has no PIPE model) and DEC-003 put the
boundary at a raw-TLP DWORD stream instead.  The real adapter therefore lives
in `tlp_stream_shim.py`, the name DEC-003 mandates; this module only re-exports
it so that either name works.
"""

from .tlp_stream_shim import TlpStreamShim, ProtocolError  # noqa: F401

PipeAdapter = TlpStreamShim
