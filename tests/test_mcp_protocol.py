import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]


async def _exercise_server() -> None:
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server.py"), "--transport", "stdio"])
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {"review_prescription", "get_lab_review_context", "calculate_egfr", "retrieve_rules", "analyze_molecular_similarity"}.issubset(names)
            result = await session.call_tool("retrieve_rules", {"drug": "ceftazidime"})
            assert result.isError is False
            context = await session.call_tool(
                "get_lab_review_context",
                {
                    "payload": {
                        "id": "MCP-CONTEXT-1",
                        "patient": {
                            "encounter_id": "ENC-1",
                            "review_time": "2026-07-28T08:00:00Z",
                            "labs": [{
                                "name": "potassium",
                                "value": 4.4,
                                "unit": "mEq/L",
                                "collected_at": "2026-07-27T08:00:00Z",
                                "encounter_id": "ENC-1",
                            }],
                        },
                        "review_targets": ["spironolactone"],
                        "medications": [{"drug": "spironolactone", "dose_mg": 25, "frequency": "qd"}],
                    }
                },
            )
            assert context.isError is False


def test_stdio_mcp_round_trip() -> None:
    asyncio.run(_exercise_server())
