import os
import requests
from typing import Dict, Any

from app.production_security import mcp_service_key

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp_server:9000")


def call_mcp_server(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Call the internal MCP gateway with its own service credential.

    Browser identities are still evaluated by the MCP PDPA policy. The service
    key only prevents a process outside the private Compose network from calling
    the gateway directly.
    """
    try:
        response = requests.post(
            f"{MCP_SERVER_URL.rstrip('/')}/mcp/call-tool",
            json=plan,
            headers={"X-MCP-Service-Key": mcp_service_key()},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return {
            "success": False,
            "error": "MCP service is temporarily unavailable. Retry shortly or ask an administrator to check system readiness.",
        }
