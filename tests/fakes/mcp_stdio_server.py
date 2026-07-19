from mcp.server.fastmcp import FastMCP


server = FastMCP("stdio-test")


@server.tool()
def multiply(left: int, right: int) -> dict[str, int]:
    """Multiply two integers."""
    return {"result": left * right}


if __name__ == "__main__":
    server.run(transport="stdio")
