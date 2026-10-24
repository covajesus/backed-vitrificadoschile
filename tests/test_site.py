from app.domain import OFF_SITE_MESSAGE, on_site
from app.geocoding import expand_street_query, places_from_google, places_from_nominatim, shorten_address


def test_twenty_meters_is_the_site_radius() -> None:
    assert on_site(-33.4, -70.5, -33.4, -70.5)
    assert not on_site(-33.4, -70.5, -33.401, -70.5)
    assert "ubicación del trabajo" in OFF_SITE_MESSAGE


def test_address_suggestions_keep_the_written_place_and_its_coordinates() -> None:
    google = places_from_google({
        "results": [{
            "formatted_address": "Av. Apoquindo 4500, Las Condes, Santiago, Región Metropolitana, 7550000, Chile",
            "address_components": [
                {"long_name": "4500", "types": ["street_number"]},
                {"long_name": "Avenida Apoquindo", "types": ["route"]},
                {"long_name": "Las Condes", "types": ["locality", "political"]},
                {"long_name": "Provincia de Santiago", "types": ["administrative_area_level_2", "political"]},
                {"long_name": "Región Metropolitana", "types": ["administrative_area_level_1", "political"]},
                {"long_name": "7550000", "types": ["postal_code"]},
                {"long_name": "Chile", "types": ["country", "political"]},
            ],
            "geometry": {"location": {"lat": -33.41, "lng": -70.58}},
        }],
    })
    nominatim = places_from_nominatim([{
        "display_name": "1980, Til Til, Barrio Bernardo O'Higgins, Ñuñoa, Santiago, Provincia de Santiago, Región Metropolitana de Santiago, 8320000, Chile",
        "lat": "-33.45",
        "lon": "-70.60",
        "address": {
            "house_number": "1980",
            "road": "Til Til",
            "neighbourhood": "Barrio Bernardo O'Higgins",
            "suburb": "Ñuñoa",
            "city": "Santiago",
            "county": "Provincia de Santiago",
            "state": "Región Metropolitana de Santiago",
            "ISO3166-2-lvl4": "CL-RM",
            "postcode": "8320000",
            "country": "Chile",
        },
    }])
    santiago = places_from_google({
        "results": [{
            "formatted_address": "Til Til 1980, Ñuñoa, Santiago, Región Metropolitana, Chile",
            "address_components": [
                {"long_name": "1980", "types": ["street_number"]},
                {"long_name": "Til Til", "types": ["route"]},
                {"long_name": "Ñuñoa", "types": ["sublocality_level_1", "sublocality", "political"]},
                {"long_name": "Santiago", "types": ["locality", "political"]},
                {"long_name": "Región Metropolitana", "types": ["administrative_area_level_1", "political"]},
                {"long_name": "Chile", "types": ["country", "political"]},
            ],
            "geometry": {"location": {"lat": -33.45, "lng": -70.60}},
        }],
    })
    coast = places_from_nominatim([{
        "lat": "-33.04",
        "lon": "-71.62",
        "address": {
            "road": "Avenida Brasil",
            "suburb": "Almendral",
            "city": "Valparaíso",
            "state": "Región de Valparaíso",
        },
    }])
    assert google[0].label == "Avenida Apoquindo 4500, Las Condes, Región Metropolitana"
    assert google[0].latitude == -33.41
    assert nominatim[0].label == "Til Til 1980, Ñuñoa, Región Metropolitana"
    assert nominatim[0].longitude == -70.60
    assert santiago[0].label == "Til Til 1980, Ñuñoa, Región Metropolitana"
    assert coast[0].label == "Avenida Brasil, Valparaíso, Región de Valparaíso"
    assert shorten_address("Av. Apoquindo 4500, Las Condes, Santiago, Región Metropolitana, 7550000, Chile") == "Av. Apoquindo 4500, Las Condes, Región Metropolitana"
    assert shorten_address("1980, Til Til, Barrio Bernardo O'Higgins, Ñuñoa, Santiago, Provincia de Santiago, Región Metropolitana de Santiago, 8320000, Chile") == "Til Til 1980, Ñuñoa, Región Metropolitana"


def test_avenue_abbreviations_search_as_avenida() -> None:
    assert expand_street_query("av apoquindo 4500") == "Avenida apoquindo 4500"
    assert expand_street_query("Av. Apoquindo 4500") == "Avenida Apoquindo 4500"
    assert expand_street_query("avda.Apoquindo") == "Avenida Apoquindo"
    assert expand_street_query("Avenida Apoquindo") == "Avenida Apoquindo"
