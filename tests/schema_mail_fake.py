"""Validate launcher RPCs using the real in-process FastMCP tools/list schema."""
import asyncio
from functools import lru_cache
from jsonschema import Draft202012Validator

@lru_cache(maxsize=1)
def tool_schemas():
    from agentstack_mail.app import build_mcp_server
    async def read():
        from fastmcp import Client
        async with Client(build_mcp_server()) as client:
            return {tool.name: tool.inputSchema for tool in await client.list_tools()}
    return asyncio.run(read())

def validate_call(name, arguments):
    schema = tool_schemas()[name]
    # FastMCP's Pydantic call validator forbids unexpected kwargs, including
    # when the JSON schema itself omits additionalProperties.
    extra = set(arguments) - set(schema.get('properties', {}))
    if extra:
        raise ValueError(f'{name}: unexpected arguments {sorted(extra)}')
    Draft202012Validator(schema).validate(arguments)
