import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp import StdioServerParameters
from smolagents import MCPClient, ToolCallingAgent
from smolagents.models import OpenAIServerModel

load_dotenv()

SERVICES_DIR = Path(__file__).parent.parent / "services"


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "Jaka jest pogoda w Krakowie?"

    model = OpenAIServerModel(model_id="gpt-4o-mini")

    server_params = [
        StdioServerParameters(
            command=sys.executable,
            args=[str(SERVICES_DIR / "location_service.py")],
        ),
        StdioServerParameters(
            command=sys.executable,
            args=[str(SERVICES_DIR / "weather_service.py")],
        ),
    ]

    with MCPClient(server_params, structured_output=True) as tools:
        agent = ToolCallingAgent(tools=tools, model=model)
        result = agent.run(query)

    print("\n--- Answer ---")
    print(result)


if __name__ == "__main__":
    main()
