"""Re-export the shared A2A client. Discovery runs at orchestrator startup."""
from delphi_common.a2a import A2AClient

__all__ = ["A2AClient"]
