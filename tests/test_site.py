from app.domain import OFF_SITE_MESSAGE, on_site
from app.geocoding import places_from_google, places_from_nominatim


def test_twenty_meters_is_the_site_radius() -> None:
    assert on_site(-33.4, -70.5, -33.4, -70.5)
    assert not on_site(-33.4, -70.5, -33.401, -70.5)
    assert "ubicación del trabajo" in OFF_SITE_MESSAGE


def test_address_suggestions_keep_the_written_place_and_its_coordinates() -> None:
    google = places_from_google({
        "results": [{
            "formatted_address": "Av. Apoquindo 4500, Las Condes, Chile",
            "geometry": {"location": {"lat": -33.41, "lng": -70.58}},
        }],
    })
    nominatim = places_from_nominatim([{
        "display_name": "Avenida Apoquindo 4500, Las Condes, Chile",
        "lat": "-33.41",
        "lon": "-70.58",
    }])
    assert google[0].label.startswith("Av. Apoquindo")
    assert google[0].latitude == -33.41
    assert nominatim[0].longitude == -70.58
