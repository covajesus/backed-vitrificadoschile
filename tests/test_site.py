from app.domain import OFF_SITE_MESSAGE, SITE_RADIUS_METERS, on_site


def test_on_site_uses_base_radius_and_gps_accuracy() -> None:
    assert SITE_RADIUS_METERS == 50
    assert on_site(-33.4, -70.5, -33.4, -70.5)
    assert on_site(-33.4, -70.5, -33.4003, -70.5)
    assert not on_site(-33.4, -70.5, -33.401, -70.5)
    assert on_site(-33.4, -70.5, -33.401, -70.5, 80)
    assert on_site(0, 0, -33.4, -70.5)
    assert "ubicación del trabajo" in OFF_SITE_MESSAGE
