import json
import os
import urllib.parse
import urllib.request
from pathlib import Path


class AddressNotFound(LookupError):
    pass


class Place:
    def __init__(self, label: str, latitude: float, longitude: float) -> None:
        self.label = label
        self.latitude = latitude
        self.longitude = longitude


def suggest_addresses(address: str) -> list[Place]:
    query = address.strip()
    if len(query) < 3:
        return []
    key = maps_key()
    if key:
        found = google_suggestions(query, key)
        if found:
            return found
    return nominatim_suggestions(query)


def places_from_google(payload: object) -> list[Place]:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    places: list[Place] = []
    for item in results[:5]:
        if not isinstance(item, dict):
            continue
        geometry = item.get("geometry")
        location = geometry.get("location") if isinstance(geometry, dict) else None
        label = item.get("formatted_address")
        if not isinstance(location, dict) or not isinstance(label, str):
            continue
        if "lat" not in location or "lng" not in location:
            continue
        places.append(Place(label, float(location["lat"]), float(location["lng"])))
    return places


def places_from_nominatim(payload: object) -> list[Place]:
    if not isinstance(payload, list):
        return []
    places: list[Place] = []
    for item in payload[:5]:
        if not isinstance(item, dict):
            continue
        label = item.get("display_name")
        if not isinstance(label, str) or "lat" not in item or "lon" not in item:
            continue
        places.append(Place(label, float(item["lat"]), float(item["lon"])))
    return places


def locate_address(address: str) -> tuple[float, float]:
    query = address.strip()
    if len(query) < 5:
        raise AddressNotFound("Indica la dirección de la obra.")
    key = maps_key()
    if key:
        return google_location(query, key)
    return nominatim_location(query)


def maps_key() -> str:
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if key:
        return key
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("GOOGLE_MAPS_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def google_location(address: str, key: str) -> tuple[float, float]:
    places = google_suggestions(address, key)
    if not places:
        raise AddressNotFound("No se encontró la dirección en Google Maps.")
    return places[0].latitude, places[0].longitude


def google_suggestions(address: str, key: str) -> list[Place]:
    params = urllib.parse.urlencode({
        "address": address,
        "region": "cl",
        "components": "country:CL",
        "language": "es",
        "key": key,
    })
    try:
        payload = fetch_json(f"https://maps.googleapis.com/maps/api/geocode/json?{params}")
    except AddressNotFound:
        return []
    return places_from_google(payload)


def nominatim_location(address: str) -> tuple[float, float]:
    places = nominatim_suggestions(address)
    if not places:
        raise AddressNotFound("No se encontró la dirección en Google Maps.")
    return places[0].latitude, places[0].longitude


def nominatim_suggestions(address: str) -> list[Place]:
    params = urllib.parse.urlencode({
        "format": "jsonv2",
        "limit": 5,
        "countrycodes": "cl",
        "addressdetails": 1,
        "q": address,
    })
    try:
        payload = fetch_json(
            f"https://nominatim.openstreetmap.org/search?{params}",
            headers={"User-Agent": "VitrificadosChile/1.0"},
        )
    except AddressNotFound:
        return []
    return places_from_nominatim(payload)


def fetch_json(url: str, headers: dict[str, str] | None = None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode())
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise AddressNotFound("No se pudo consultar la ubicación.") from error
