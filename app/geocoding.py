import json
import os
import re
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


# Soft bias around Gran Santiago when the query does not name another city/region.
SANTIAGO_VIEWBOX = "-70.98,-33.28,-70.40,-33.72"
SANTIAGO_BOUNDS = "-33.72,-70.98|-33.28,-70.40"


def expand_street_query(query: str) -> str:
    text = re.sub(r"(?i)(?<!\w)av(?:da)?\.(?=\w)", "Avenida ", query)
    return re.sub(r"(?i)(?<!\w)av(?:da)?\.?(?!\w)", "Avenida", text)


def house_number(query: str) -> str:
    head = query.split(",", 1)[0].strip()
    match = re.search(r"(?i)(?:^|\s)(\d{1,5}[A-Za-z]?)$", head)
    return match.group(1) if match else ""


def names_other_region(query: str) -> bool:
    lowered = query.casefold()
    if "metropolitana" in lowered or "santiago" in lowered:
        return False
    markers = (
        "arica", "iquique", "antofagasta", "copiap", "la serena", "coquimbo",
        "valpara", "viña", "vina del mar", "rancagua", "talca", "chillán", "chillan",
        "concepci", "talcahuano", "temuco", "valdivia", "osorno", "puerto montt",
        "coyhaique", "punta arenas", "biobío", "biobio", "ñuble", "nuble",
        "araucanía", "araucania", "los lagos", "los ríos", "los rios", "magallanes",
        "atacama", "tarapac", "aisen", "aysén", "aysen",
    )
    return any(marker in lowered for marker in markers)


def with_santiago_bias(query: str) -> str:
    if names_other_region(query):
        return query
    lowered = query.casefold()
    if "santiago" in lowered or "metropolitana" in lowered:
        return query
    if "," in query:
        return f"{query}, Chile"
    return f"{query}, Santiago, Chile"


def suggest_addresses(address: str) -> list[Place]:
    query = expand_street_query(address.strip())
    if len(query) < 3:
        return []
    key = maps_key()
    if key:
        found = google_suggestions(query, key)
        if found:
            return rank_places(query, found)
    return rank_places(query, nominatim_suggestions(query))


def places_from_google(payload: object) -> list[Place]:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    places: list[Place] = []
    for item in results[:8]:
        if not isinstance(item, dict):
            continue
        geometry = item.get("geometry")
        location = geometry.get("location") if isinstance(geometry, dict) else None
        label = google_label(item)
        if not isinstance(location, dict) or not label:
            continue
        if "lat" not in location or "lng" not in location:
            continue
        places.append(Place(label, float(location["lat"]), float(location["lng"])))
    return places


def places_from_nominatim(payload: object) -> list[Place]:
    if not isinstance(payload, list):
        return []
    places: list[Place] = []
    for item in payload[:8]:
        if not isinstance(item, dict):
            continue
        label = nominatim_label(item)
        if not label or "lat" not in item or "lon" not in item:
            continue
        places.append(Place(label, float(item["lat"]), float(item["lon"])))
    return places


def google_label(item: dict) -> str:
    components = item.get("address_components")
    if isinstance(components, list):
        label = label_from_google(components)
        if label:
            return label
    formatted = item.get("formatted_address")
    return shorten_address(formatted) if isinstance(formatted, str) else ""


def nominatim_label(item: dict) -> str:
    details = item.get("address")
    if isinstance(details, dict):
        label = label_from_nominatim(details)
        if label:
            return label
    display = item.get("display_name")
    return shorten_address(display) if isinstance(display, str) else ""


def label_from_google(components: list) -> str:
    street = join_street(component_name(components, "route"), component_name(components, "street_number"))
    locality = component_name(components, "locality")
    specific = component_name(components, "sublocality_level_1", "sublocality", "administrative_area_level_3")
    comuna = specific if locality.casefold() == "santiago" and specific else (locality or specific)
    region = region_name(component_name(components, "administrative_area_level_1"))
    return join_place(street, comuna, region)


def label_from_nominatim(details: dict) -> str:
    street = join_street(
        detail_name(details, "road", "pedestrian", "residential", "footway"),
        text(details.get("house_number")),
    )
    region = region_name(text(details.get("state")))
    return join_place(street, comuna_from_nominatim(details), region)


def comuna_from_nominatim(details: dict) -> str:
    state = text(details.get("state"))
    code = text(details.get("ISO3166-2-lvl4"))
    if metro_region(state, code):
        return detail_name(details, "suburb", "city_district", "municipality", "borough", "town") or text(details.get("city"))
    return detail_name(details, "city", "town", "municipality", "village") or detail_name(details, "suburb", "city_district")


def metro_region(state: str, code: str = "") -> bool:
    lowered = state.casefold()
    return code.casefold() == "cl-rm" or lowered.startswith("región metropolitana") or lowered.startswith("region metropolitana")


def component_name(components: list, *types: str) -> str:
    for wanted in types:
        for component in components:
            if not isinstance(component, dict):
                continue
            names = component.get("types")
            if isinstance(names, list) and wanted in names:
                return text(component.get("long_name"))
    return ""


def detail_name(details: dict, *keys: str) -> str:
    for key in keys:
        value = text(details.get(key))
        if value:
            return value
    return ""


def join_street(road: str, number: str) -> str:
    return " ".join(part for part in (road.strip(), number.strip()) if part)


def region_name(value: str) -> str:
    cleaned = value.strip()
    lowered = cleaned.casefold()
    if lowered.startswith("región metropolitana") or lowered.startswith("region metropolitana"):
        return "Región Metropolitana"
    return cleaned


def join_place(street: str, comuna: str, city: str) -> str:
    parts: list[str] = []
    for part in (street, comuna, city):
        cleaned = part.strip()
        if not cleaned or cleaned.isdigit():
            continue
        if any(cleaned.casefold() == current.casefold() for current in parts):
            continue
        parts.append(cleaned)
    return ", ".join(parts)


def shorten_address(value: str) -> str:
    parts: list[str] = []
    region = ""
    for raw in value.split(","):
        part = raw.strip()
        lowered = part.casefold()
        if not part or lowered in {"chile"}:
            continue
        if lowered.startswith(("código", "codigo")):
            continue
        if lowered.startswith(("región", "region")):
            region = region_name(part)
            continue
        if lowered.startswith("provincia"):
            continue
        parts.append(part)
    if len(parts) >= 2 and parts[0].isdigit():
        parts = [f"{parts[1]} {parts[0]}", *parts[2:]]
    street = parts[0] if parts else ""
    places = [part for part in parts[1:] if not part.casefold().startswith("barrio ")]
    santiago = next((index for index, part in enumerate(places) if part.casefold() == "santiago"), -1)
    if santiago > 0:
        comuna = places[santiago - 1]
    elif places:
        comuna = places[-1]
    else:
        comuna = ""
    return join_place(street, comuna, region)


def text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def keep_house_number(place: Place, query: str) -> Place:
    number = house_number(query)
    if not number or re.search(rf"(?i)\b{re.escape(number)}\b", place.label):
        return place
    street, _, rest = place.label.partition(",")
    street = street.strip()
    if not street or street[-1].isdigit():
        return place
    query_street = re.sub(rf"(?i)\s*{re.escape(number)}\s*$", "", query.split(",", 1)[0]).strip()
    if query_street and query_street.casefold() not in street.casefold() and street.casefold() not in query_street.casefold():
        return place
    labeled = f"{street} {number}"
    if rest.strip():
        labeled = f"{labeled}, {rest.strip()}"
    return Place(labeled, place.latitude, place.longitude)


def place_score(query: str, place: Place) -> tuple[int, int, str]:
    label = place.label.casefold()
    number = house_number(query).casefold()
    score = 0
    if "región metropolitana" in label or "region metropolitana" in label:
        score += 40
    if "santiago" in label:
        score += 10
    if number and re.search(rf"\b{re.escape(number)}\b", label):
        score += 30
    street = query.split(",", 1)[0]
    street = re.sub(rf"(?i)\s*{re.escape(number)}\s*$", "", street).strip().casefold() if number else street.casefold()
    if street and street in label:
        score += 20
    # Prefer points inside a loose Santiago box.
    if -33.75 <= place.latitude <= -33.25 and -71.05 <= place.longitude <= -70.35:
        score += 25
    return (-score, len(place.label), place.label.casefold())


def dedupe_places(places: list[Place]) -> list[Place]:
    seen: set[str] = set()
    unique: list[Place] = []
    for place in places:
        key = re.sub(r"\s+", " ", place.label.casefold())
        key = re.sub(r"[^\wáéíóúñü ,]", "", key)
        coord = f"{round(place.latitude, 5)},{round(place.longitude, 5)}"
        marker = f"{key}|{coord}"
        if marker in seen or key in seen:
            continue
        seen.add(marker)
        seen.add(key)
        unique.append(place)
    return unique


def rank_places(query: str, places: list[Place]) -> list[Place]:
    numbered = [keep_house_number(place, query) for place in places]
    ordered = sorted(dedupe_places(numbered), key=lambda place: place_score(query, place))
    return ordered[:5]


def locate_address(address: str) -> tuple[float, float]:
    query = expand_street_query(address.strip())
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
    ranked = rank_places(address, places)
    return ranked[0].latitude, ranked[0].longitude


def google_suggestions(address: str, key: str) -> list[Place]:
    queries = [address]
    biased = with_santiago_bias(address)
    if biased != address:
        queries.append(biased)
    places: list[Place] = []
    for query in queries:
        params = {
            "address": query,
            "region": "cl",
            "components": "country:CL",
            "language": "es",
            "key": key,
        }
        if not names_other_region(address):
            params["bounds"] = SANTIAGO_BOUNDS
        encoded = urllib.parse.urlencode(params)
        try:
            payload = fetch_json(f"https://maps.googleapis.com/maps/api/geocode/json?{encoded}")
        except AddressNotFound:
            continue
        places.extend(places_from_google(payload))
    return places


def nominatim_location(address: str) -> tuple[float, float]:
    places = nominatim_suggestions(address)
    if not places:
        raise AddressNotFound("No se encontró la dirección en Google Maps.")
    ranked = rank_places(address, places)
    return ranked[0].latitude, ranked[0].longitude


def nominatim_search(query: str, *, viewbox: str | None = None) -> list[Place]:
    params: dict[str, str] = {
        "format": "jsonv2",
        "limit": "8",
        "countrycodes": "cl",
        "addressdetails": "1",
        "q": query,
    }
    if viewbox:
        params["viewbox"] = viewbox
        params["bounded"] = "0"
    encoded = urllib.parse.urlencode(params)
    try:
        payload = fetch_json(
            f"https://nominatim.openstreetmap.org/search?{encoded}",
            headers={"User-Agent": "VitrificadosChile/1.0"},
        )
    except AddressNotFound:
        return []
    return places_from_nominatim(payload)


def nominatim_suggestions(address: str) -> list[Place]:
    places: list[Place] = []
    if not names_other_region(address):
        places.extend(nominatim_search(address, viewbox=SANTIAGO_VIEWBOX))
        biased = with_santiago_bias(address)
        if biased != address:
            places.extend(nominatim_search(biased, viewbox=SANTIAGO_VIEWBOX))
    places.extend(nominatim_search(address))
    return places


def fetch_json(url: str, headers: dict[str, str] | None = None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode())
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise AddressNotFound("No se pudo consultar la ubicación.") from error
