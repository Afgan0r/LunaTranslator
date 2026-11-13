"""Compatibility alias for the shared integration module."""
import sys
from integrations import engine as _module
sys.modules[__name__] = _module
