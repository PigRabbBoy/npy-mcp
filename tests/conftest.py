"""Pytest config — ensure unpy-core src on path for all tests."""

import os
import sys

# Ensure unpy-core is importable
_CORE_SRC = os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-core", "src")
_CORE_SRC = os.path.abspath(_CORE_SRC)
if _CORE_SRC not in sys.path:
    sys.path.insert(0, _CORE_SRC)

# Ensure unpy-cli is importable
_CLI_SRC = os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-cli", "src")
_CLI_SRC = os.path.abspath(_CLI_SRC)
if _CLI_SRC not in sys.path:
    sys.path.insert(0, _CLI_SRC)

# Ensure npy-mcp is importable
_MCP_SRC = os.path.join(os.path.dirname(__file__), "..", "packages", "npy-mcp", "src")
_MCP_SRC = os.path.abspath(_MCP_SRC)
if _MCP_SRC not in sys.path:
    sys.path.insert(0, _MCP_SRC)