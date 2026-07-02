"""Test setup: make `orchestrator/` importable and set dummy env.

Tests run with no network and no live LLM/DB. Persistence nodes fire-and-forget,
so a missing DATABASE_URL is caught and logged (never raised).
"""
import os
import sys
from pathlib import Path

ORCH_ROOT = Path(__file__).resolve().parent.parent
if str(ORCH_ROOT) not in sys.path:
    sys.path.insert(0, str(ORCH_ROOT))

# Dummy LLM env so any accidental client construction doesn't KeyError.
os.environ.setdefault("LLM_BASE_URL", "http://test.local/v1")
os.environ.setdefault("LLM_API_KEY", "TEST")
os.environ.setdefault("LLM_MODEL", "test-model")
os.environ.setdefault("LLM_TIMEOUT_SECONDS", "5")
# DATABASE_URL intentionally left UNSET -> persistence fails fast & is caught.
