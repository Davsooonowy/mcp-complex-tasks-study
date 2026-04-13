from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather-service")

# Hardcoded weather data keyed by (lat, lon) rounded to 2 decimal places.
# Coordinates match the values returned by location_service.py.
WEATHER_DATA: dict[tuple[float, float], dict] = {
    (50.06, 19.95): {
        "city": "Kraków",
        "temperature_celsius": 12,
        "condition": "partly cloudy",
        "humidity_percent": 65,
        "wind_kmh": 18,
    },
    (52.23, 21.01): {
        "city": "Warszawa",
        "temperature_celsius": 9,
        "condition": "rainy",
        "humidity_percent": 80,
        "wind_kmh": 22,
    },
    (54.35, 18.65): {
        "city": "Gdańsk",
        "temperature_celsius": 7,
        "condition": "cloudy",
        "humidity_percent": 75,
        "wind_kmh": 30,
    },
    (51.11, 17.04): {
        "city": "Wrocław",
        "temperature_celsius": 11,
        "condition": "sunny",
        "humidity_percent": 55,
        "wind_kmh": 12,
    },
}


@mcp.tool()
def get_weather(lat: float, lon: float) -> str:
    """Get current weather conditions for the given geographic coordinates.

    Args:
        lat: Latitude of the location.
        lon: Longitude of the location.

    Returns:
        A string describing current weather, or an error message if no data is available.
    """
    key = (round(lat, 2), round(lon, 2))
    data = WEATHER_DATA.get(key)
    if data:
        return (
            f"Weather in {data['city']}: "
            f"{data['temperature_celsius']}°C, "
            f"{data['condition']}, "
            f"humidity {data['humidity_percent']}%, "
            f"wind {data['wind_kmh']} km/h."
        )
    return f"No weather data available for coordinates lat={lat}, lon={lon}."


if __name__ == "__main__":
    mcp.run(transport="stdio")
