from typing import Any
import argparse

import httpx
import uvicorn  # ASGI server
from mcp.server import Server  # Base server class
from mcp.server.fastmcp import FastMCP  # Main MCP server class
from mcp.server.sse import SseServerTransport  # SSE transport implementation
from starlette.applications import Starlette  # ASGI framework
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Mount, Route

# Initialize FastMCP server with a name
# This name appears to clients when they connect
mcp = FastMCP("weather")

# Constants for API access
NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-app/1.0"  # Required by NWS API


async def make_nws_request(url: str) -> dict[str, Any] | None:
    """Make a request to the NWS API with proper error handling.

    This helper function centralizes API communication logic and error handling.
    """
    headers = {
        "User-Agent": USER_AGENT,  # NWS requires a user agent
        "Accept": "application/geo+json",  # Request GeoJSON format
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None  # Return None on any error


def format_alert(feature: dict) -> str:
    """Format an alert feature into a readable string.

    Extracts and formats the most important information from an alert.
    """
    props = feature["properties"]
    return f"""
Event: {props.get("event", "Unknown")}
Area: {props.get("areaDesc", "Unknown")}
Severity: {props.get("severity", "Unknown")}
Description: {props.get("description", "No description available")}
Instructions: {props.get("instruction", "No specific instructions provided")}
"""


# Define a tool using the @mcp.tool() decorator
# This makes the function available as a callable tool to MCP clients
@mcp.tool()
async def get_alerts(state: str) -> str:
    """Get weather alerts for a US state.

    Args:
        state: Two-letter US state code (e.g. CA, NY)
    """
    url = f"{NWS_API_BASE}/alerts/active/area/{state}"
    data = await make_nws_request(url)

    if not data or "features" not in data:
        return "Unable to fetch alerts or no alerts found."

    if not data["features"]:
        return "No active alerts for this state."

    alerts = [format_alert(feature) for feature in data["features"]]
    return "\n---\n".join(alerts)


# Define another tool
@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str:
    """Get weather forecast for a location.

    Args:
        latitude: Latitude of the location
        longitude: Longitude of the location
    """
    # First get the forecast grid endpoint
    points_url = f"{NWS_API_BASE}/points/{latitude},{longitude}"
    points_data = await make_nws_request(points_url)

    if not points_data:
        return "Unable to fetch forecast data for this location."

    # Get the forecast URL from the points response
    forecast_url = points_data["properties"]["forecast"]
    forecast_data = await make_nws_request(forecast_url)

    if not forecast_data:
        return "Unable to fetch detailed forecast."

    # Format the periods into a readable forecast
    periods = forecast_data["properties"]["periods"]
    forecasts = []
    for period in periods[:5]:  # Only show next 5 periods
        forecast = f"""
{period["name"]}:
Temperature: {period["temperature"]}°{period["temperatureUnit"]}
Wind: {period["windSpeed"]} {period["windDirection"]}
Forecast: {period["detailedForecast"]}
"""
        forecasts.append(forecast)

    return "\n---\n".join(forecasts)


# HTML for the homepage that displays "MCP Server"
async def homepage(request: Request) -> HTMLResponse:
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MCP Server</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
            }
            h1 {
                margin-bottom: 10px;
            }
            button {
                background-color: #f8f8f8;
                border: 1px solid #ccc;
                padding: 8px 16px;
                margin: 10px 0;
                cursor: pointer;
                border-radius: 4px;
            }
            button:hover {
                background-color: #e8e8e8;
            }
            .status {
                border: 1px solid #ccc;
                padding: 10px;
                min-height: 20px;
                margin-top: 10px;
                border-radius: 4px;
                color: #555;
            }
        </style>
    </head>
    <body>
        <h1>MCP Server</h1>

        <p>Server is running correctly!</p>

        <button id="connect-button">Connect to SSE</button>

        <div class="status" id="status">Connection status will appear here...</div>

        <script>
            document.getElementById('connect-button').addEventListener('click', function() {
                // Redirect to the SSE connection page or initiate the connection
                const statusDiv = document.getElementById('status');

                try {
                    const eventSource = new EventSource('/sse');

                    statusDiv.textContent = 'Connecting...';

                    eventSource.onopen = function() {
                        statusDiv.textContent = 'Connected to SSE';
                    };

                    eventSource.onerror = function() {
                        statusDiv.textContent = 'Error connecting to SSE';
                        eventSource.close();
                    };

                    eventSource.onmessage = function(event) {
                        statusDiv.textContent = 'Received: ' + event.data;
                    };

                    // Add a disconnect option
                    const disconnectButton = document.createElement('button');
                    disconnectButton.textContent = 'Disconnect';
                    disconnectButton.addEventListener('click', function() {
                        eventSource.close();
                        statusDiv.textContent = 'Disconnected';
                        this.remove();
                    });

                    document.body.appendChild(disconnectButton);

                } catch (e) {
                    statusDiv.textContent = 'Error: ' + e.message;
                }
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(html_content)


# Create a Starlette application with SSE transport
def create_starlette_app(mcp_server: Server, *, debug: bool = False) -> Starlette:
    """Create a Starlette application that can server the provied mcp server with SSE.

    This sets up the HTTP routes and SSE connection handling.
    """
    # Create an SSE transport with a path for messages
    sse = SseServerTransport("/messages/")

    # Handler for SSE connections
    async def handle_sse(request: Request) -> None:
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,  # access private method
        ) as (read_stream, write_stream):
            # Run the MCP server with the SSE streams
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    # Create and return the Starlette application
    return Starlette(
        debug=debug,
        routes=[
            Route("/", endpoint=homepage),  # Add the homepage route
            Route("/sse", endpoint=handle_sse),  # Endpoint for SSE connections
            Mount("/messages/", app=sse.handle_post_message),  # Endpoint for messages
        ],
    )


mcp_server = mcp._mcp_server


# Parse command-line arguments
parser = argparse.ArgumentParser(description="Run MCP SSE-based server")
parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
args = parser.parse_args()

# Create and run the Starlette application
app = create_starlette_app(mcp_server, debug=True)
uvicorn.run(app, host=args.host, port=args.port)
