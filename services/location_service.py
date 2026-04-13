from mcp.server.fastmcp import FastMCP

mcp = FastMCP("location-service")

CITIES: dict[str, dict[str, float]] = {
    "kraków": {"lat": 50.0647, "lon": 19.9450},
    "krakow": {"lat": 50.0647, "lon": 19.9450},
    "warszawa": {"lat": 52.2297, "lon": 21.0122},
    "warsaw": {"lat": 52.2297, "lon": 21.0122},
    "gdańsk": {"lat": 54.3520, "lon": 18.6466},
    "gdansk": {"lat": 54.3520, "lon": 18.6466},
    "wrocław": {"lat": 51.1079, "lon": 17.0385},
    "wroclaw": {"lat": 51.1079, "lon": 17.0385},
}


@mcp.tool()
def get_coordinates(city: str) -> str:
    """Get geographic coordinates (latitude and longitude) for a Polish city.

    Args:
        city: Name of the city (supports Kraków, Warszawa, Gdańsk, Wrocław).

    Returns:
        A string with latitude and longitude, or an error message if the city is unknown.
    """
    key = city.lower().strip()
    coords = CITIES.get(key)
    if coords:
        return f"latitude={coords['lat']}, longitude={coords['lon']}"
    available = "Kraków, Warszawa, Gdańsk, Wrocław"
    return f"City '{city}' not found. Available cities: {available}."


if __name__ == "__main__":
    mcp.run(transport="stdio")
