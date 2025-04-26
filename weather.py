import os
from typing import Any
from datetime import datetime

import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from mcp.server import Server
from dotenv import load_dotenv

load_dotenv()

mcp = FastMCP(
    name="weather", description="MCP for weather forecast for 3 days", version="1.0.0"
)

WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
WEATHER_API_BASE = "https://api.weatherapi.com/v1"
NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-app/1.0"


async def make_weather_request(url: str) -> dict[str, Any] | None:
    """Make a request to the NWS API with proper error handling"""

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None


@mcp.tool()
async def get_forecast(location: str) -> str:
    """Get weather forecast for a location.

    Args:
        location: Location as longitude,latitude e.g. "48.8567,2.3508" or city name e.g. "Paris" or IP address
    """

    url = f"{WEATHER_API_BASE}/forecast.json?key={WEATHER_API_KEY}&q={location}&days=3&hour={datetime.now().hour}"
    weather_data = await make_weather_request(url)

    if not weather_data:
        return "Unable to fetch forecast data for this locaiton"

    forecasts = weather_data["forecast"]["forecastday"]
    pretty = []
    for forecast in forecasts:
        val = f"""
{forecast["hour"][0]["time"]}:
Temperature: {forecast["day"]["avgtemp_c"]}°C
Max Wind: {forecast["day"]["maxwind_kph"]} kph
Chance of rain: {forecast["day"]["daily_will_it_rain"]}
Chance of snow: {forecast["day"]["daily_will_it_snow"]}
UV: {forecast["day"]["uv"]}
"""
        pretty.append(val)

    return "\n--\n".join(pretty)


async def homepage(request: Request) -> HTMLResponse:
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MCP Weather</title>
        <style>
        body {
            display: grid;
            place: center;
        }
        </style>
    </head>
    <body>
        <h1>MCP Weather</h1>
        <p>An MCP to get weather forecasts for the next 3 days for any city</p>
    </body>
    """
    return HTMLResponse(html_content)


def create_starlette_app(mcp_server: Server, *, debug: bool = False) -> Starlette:
    """Create a Starlette application that can serve the provided mcp server with SSE."""
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> None:
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    return Starlette(
        debug=debug,
        routes=[
            Route("/", endpoint=homepage),  # Add the homepage route
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )


if __name__ == "__main__":
    mcp_server = mcp._mcp_server

    app = create_starlette_app(mcp_server, debug=True)

    uvicorn.run(app, host="0.0.0.0", port=8080)
