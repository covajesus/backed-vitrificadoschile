from app.geocoding import (
    Place,
    house_number,
    keep_house_number,
    names_other_region,
    rank_places,
    with_santiago_bias,
)


def test_house_number_and_santiago_bias() -> None:
    assert house_number("Los Araucanos 2401") == "2401"
    assert house_number("Los Araucanos 2401, Santiago") == "2401"
    assert house_number("Avenida Apoquindo") == ""
    assert with_santiago_bias("Los Araucanos 2401") == "Los Araucanos 2401, Santiago, Chile"
    assert with_santiago_bias("Los Araucanos, Arica") == "Los Araucanos, Arica"
    assert names_other_region("Los Araucanos, Talcahuano")
    assert not names_other_region("Los Araucanos 2401")


def test_rank_places_prefers_metro_and_keeps_number() -> None:
    places = [
        Place("Los Araucanos, Arica, Región de Arica y Parinacota", -18.43, -70.29),
        Place("Los Araucanos, Talcahuano, Región del Biobío", -36.72, -73.13),
        Place("Los Araucanos, Providencia, Región Metropolitana", -33.42, -70.61),
        Place("Los Araucanos, Providencia, Región Metropolitana", -33.42, -70.61),
    ]
    ranked = rank_places("Los Araucanos 2401", places)
    assert ranked[0].label == "Los Araucanos 2401, Providencia, Región Metropolitana"
    assert all("Talcahuano" not in place.label or index > 0 for index, place in enumerate(ranked))
    assert len(ranked) == 3


def test_keep_house_number_only_when_street_matches() -> None:
    kept = keep_house_number(
        Place("Los Araucanos, Maipú, Región Metropolitana", -33.5, -70.7),
        "Los Araucanos 2401",
    )
    assert kept.label.startswith("Los Araucanos 2401")
    skipped = keep_house_number(
        Place("Otra Calle, Maipú, Región Metropolitana", -33.5, -70.7),
        "Los Araucanos 2401",
    )
    assert skipped.label.startswith("Otra Calle")
