r"""
Orchestrator: bridges the Civ V DLL (named pipe) and the Agent runtime.

Reads newline-delimited JSON state messages, validates them, and responds with
newline-delimited JSON actions. Pipe name defaults to \\.\pipe\civv_llm or the
CIVV_PIPE environment variable.
"""

