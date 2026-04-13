# Weather MCP Agent

A prototype demonstrating AI agent integration with the **Model Context Protocol (MCP)**. An AI agent answers natural language weather queries (e.g. *"Jaka jest pogoda w Krakowie?"*) by orchestrating two independent MCP services.

## Architecture

```
┌─────────────────────────────────────────────┐
│               agent/main.py                  │
│  ToolCallingAgent (smolagents)               │
│  Model: gpt-4o-mini (OpenAI)                │
└────────────┬─────────────────┬──────────────┘
             │ stdio MCP       │ stdio MCP
             ▼                 ▼
┌────────────────────┐ ┌──────────────────────┐
│  location_service  │ │   weather_service    │
│  get_coordinates() │ │   get_weather()      │
│  city → lat/lon    │ │   lat/lon → weather  │
└────────────────────┘ └──────────────────────┘
```

**Flow for "Jaka jest pogoda w Krakowie?":**
1. Agent calls `get_coordinates("Kraków")` → `latitude=50.0647, longitude=19.945`
2. Agent calls `get_weather(50.0647, 19.945)` → `12°C, partly cloudy, humidity 65%, wind 18 km/h`
3. Agent returns a natural language answer

## Tech stack

| Component | Library |
|-----------|---------|
| Agent framework | [smolagents](https://github.com/huggingface/smolagents) |
| MCP protocol | [mcp](https://github.com/modelcontextprotocol/python-sdk) |
| LLM | OpenAI `gpt-4o-mini` via `smolagents[openai]` |
| MCP↔smolagents bridge | `mcpadapt` (installed via `smolagents[mcp]`) |
| Package manager | [uv](https://docs.astral.sh/uv/) |

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- OpenAI API key

## Setup

```bash
# 1. Install dependencies
uv sync

# 2. Create .env file
cp .env.example .env
# Edit .env and set your key:
# OPENAI_API_KEY=sk-...
```

## Usage

```bash
# Default query (Kraków)
uv run python agent/main.py

# Custom query
uv run python agent/main.py "Jaka jest pogoda w Gdańsku?"
uv run python agent/main.py "What is the weather in Warsaw?"
```

**Supported cities:** Kraków, Warszawa, Gdańsk, Wrocław

## Project structure

```
weather-mcp-agent/
├── agent/
│   └── main.py               # Entry point — ToolCallingAgent + MCPClient
├── services/
│   ├── location_service.py   # MCP server: get_coordinates(city)
│   └── weather_service.py    # MCP server: get_weather(lat, lon)
├── .env.example              # API key template
└── pyproject.toml
```

## Key concepts

**MCP (Model Context Protocol)** — an open standard for exposing tools/resources to AI agents. Each service runs as a separate process and communicates over stdio. The agent discovers available tools at startup and decides autonomously which to call and in what order.

**smolagents** — a lightweight HuggingFace framework for building tool-calling agents. `MCPClient` connects to MCP servers and wraps their tools as native smolagents tools. `ToolCallingAgent` handles the reasoning loop: think → call tool → observe result → repeat until done.
