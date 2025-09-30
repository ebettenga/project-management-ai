"""FastMCP server exposing Jira account lookup helpers."""

from __future__ import annotations

import logging
import os
from typing import List, Optional

import requests
from requests.auth import HTTPBasicAuth
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

mcp = FastMCP("Jira User Information Tools")


class JiraUserEntry(BaseModel):
    account_id: str = Field(alias="accountId")
    email: Optional[str] = Field(default=None, alias="emailAddress")
    username: Optional[str] = None  # Only available for server/DC or older accounts

    model_config = {
        "populate_by_name": True,
    }

def _build_client() -> tuple[str, HTTPBasicAuth]:
    base_url = os.environ.get("JIRA_URL")
    username = os.environ.get("JIRA_USERNAME") or os.environ.get("JIRA_EMAIL")
    api_token = os.environ.get("JIRA_API_TOKEN")

    if not base_url:
        raise RuntimeError("JIRA_URL environment variable is required for Jira tools")
    if not username:
        raise RuntimeError(
            "JIRA_USERNAME (or JIRA_EMAIL) environment variable is required for Jira tools"
        )
    if not api_token:
        raise RuntimeError(
            "JIRA_API_TOKEN environment variable is required for Jira tools"
        )

    normalized = base_url.rstrip("/")
    auth = HTTPBasicAuth(username, api_token)
    return normalized, auth


@mcp.tool()
def get_jira_users() -> List[JiraUserEntry]:
    """
    Returns useful information about users in jira (accountId, email, username).
    
    useful when needed to perform an action on a users behalf
    """

    base_url, auth = _build_client()
    url = f"{base_url}/rest/api/3/users/search"

    try:
        response = requests.get(
            url,
            auth=auth,
            headers={"Accept": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to contact Jira API: {exc}") from exc

    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected Jira API response: expected a list")

    results: List[JiraUserEntry] = []
    for item in payload:
        # Skip non-human accounts
        if item.get("accountType") != "atlassian":
            continue
        try:
            results.append(JiraUserEntry.model_validate(item))
        except Exception as exc:
            logger.warning("Failed to parse Jira user entry %s: %s", item, exc)

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="stdio")
