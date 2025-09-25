# math_server.py
from mcp.server.fastmcp import FastMCP
from datetime import datetime, timezone

mcp = FastMCP("Date and Time Helper Functions")

@mcp.tool()
def get_datetime() -> datetime:
    """
    returns the current datetime in utc
    """
    return datetime.now(timezone.utc)

if __name__ == "__main__":
    mcp.run(transport="stdio")