"""The storm feature builder implements docs/audit/M2_FEATURE_CONTRACT.md (§7, tests 1-10)."""
import logging
import math
from datetime import datetime, timezone

import pytest

from backend.app.pipeline.features import (
    FEATURE_COLUMNS, KTS_TO_MPH, build_features, label_from_alertlevel, split_by_start, training_rows,
)

REMOVED = {
    "gdacs_alert_score", "gdacs_population_exposure", "event_category_encoded", "geometry_type_encoded",
    "acres_burned", "pct_contained", "volcano_alert_encoded", "wind_speed_mph", "storm_category",
    "persons_affected", "casualties", "ner_location_count", "ner_org_count",
}


def at(day, hour=0):
    return datetime(2024, 9, day, hour, tzinfo=timezone.utc)


def point(day, kts=None, hour=0, lat=15.0, unit="kts"):
    p = {"date": at(day, hour).isoformat().replace("+00:00", "Z"), "type": "Point", "coordinates": [130.0, lat]}
    if kts is not None:
        p.update(magnitudeValue=kts, magnitudeUnit=unit)
    return p


def storm(*points, category="Severe Storms", event_id="EONET_S1"):
    return {"id": event_id, "title": "Typhoon Test", "categories": [{"title": category}],
            "sources": [{"id": "JTWC"}, {"id": "GDACS"}], "geometry": list(points)}


def test_keys_are_the_contract_in_order():
    features = build_features(storm(point(1, 40)))
    assert list(features) == FEATURE_COLUMNS
    assert not REMOVED & set(features)
    assert len(FEATURE_COLUMNS) == 8


def test_kts_converted_to_mph():
    assert build_features(storm(point(1, 100)))["wind_max_mph"] == pytest.approx(115.078)
    assert KTS_TO_MPH == 1.15078


def test_later_points_never_change_earlier_features():
    early = storm(point(1, 40), point(2, 60))
    later = storm(point(1, 40), point(2, 60), point(3, 140, lat=-5.0))
    as_of = at(2)
    assert build_features(early, as_of=as_of) == build_features(later, as_of=as_of)


def test_max_and_latest_differ_when_peak_is_not_last():
    features = build_features(storm(point(1, 50), point(2, 120), point(3, 80)))
    assert features["wind_max_mph"] == pytest.approx(120 * KTS_TO_MPH)
    assert features["wind_latest_mph"] == pytest.approx(80 * KTS_TO_MPH)


def test_trend():
    assert math.isnan(build_features(storm(point(1, 40), point(1, 50, hour=12)))["wind_trend_mph_per_day"])

    rising = build_features(storm(point(1, 40), point(1, 50, hour=12), point(3, 100)))
    # Compared with the latest kts point at least 24 h earlier (day 1, 12:00), 1.5 days before
    assert rising["wind_trend_mph_per_day"] == pytest.approx((100 - 50) * KTS_TO_MPH / 1.5)

    falling = build_features(storm(point(1, 100), point(3, 60)))
    assert falling["wind_trend_mph_per_day"] == pytest.approx(-20 * KTS_TO_MPH)


def test_duration():
    assert build_features(storm(point(1, 40)))["event_duration_days"] == 0.0
    track = storm(point(1, 40), point(2, 50, hour=12), point(4, 60))
    assert build_features(track)["event_duration_days"] == 3.0
    # Measured from the first point to t, not to the last point
    assert build_features(track, as_of=at(3))["event_duration_days"] == 2.0


def test_missing_wind_is_nan_and_counted(caplog):
    features = build_features(storm(point(1), point(2)))
    for name in ("wind_max_mph", "wind_latest_mph", "wind_trend_mph_per_day"):
        assert math.isnan(features[name])

    with caplog.at_level(logging.WARNING):
        mixed = build_features(storm(point(1, 40), point(2, 75, unit="km/h"), point(3)))
    assert mixed["wind_max_mph"] == pytest.approx(40 * KTS_TO_MPH)
    assert mixed["wind_latest_mph"] == pytest.approx(40 * KTS_TO_MPH)
    assert "2 track point(s) without a kts wind skipped" in caplog.text


def test_hemisphere():
    assert build_features(storm(point(1, 40, lat=0.0)))["hemisphere"] == 0
    south = build_features(storm(point(1, 40, lat=-12.5)))
    assert (south["latitude"], south["hemisphere"]) == (-12.5, 1)


def test_month_and_sources():
    features = build_features(storm(point(1, 40)))
    assert features["month"] == 9
    assert features["source_count"] == 2


@pytest.mark.parametrize("category", ["Wildfires", "Volcanoes", "Floods", "Earthquakes"])
def test_other_categories_get_no_features(category):
    assert build_features(storm(point(1, 40), category=category)) is None


def test_no_point_at_or_before_t():
    with pytest.raises(ValueError):
        build_features(storm(point(2, 40)), as_of=at(1))


def test_training_rows():
    track = storm(point(1, 40), point(2, 60), point(3, 120))
    rows = training_rows(track, "Orange")
    assert len(rows) == 3
    for j, r in enumerate(rows):
        assert {k: r[k] for k in FEATURE_COLUMNS} == build_features(
            storm(*track["geometry"][:j + 1]), as_of=at(j + 1))
    assert {r["label"] for r in rows} == {1}
    assert sum(r["weight"] for r in rows) == pytest.approx(1.0)


def test_labels_upper_cased():
    assert [label_from_alertlevel(a) for a in ("Green", "GREEN", "Orange", "RED")] == [0, 0, 1, 2]


def test_split_never_puts_a_storm_on_both_sides():
    # A storm that spans the cutoff stays wholly on the side of its start
    spanning = training_rows(storm(point(1, 40), point(5, 60), event_id="A"), "Green")
    later = training_rows(storm(point(6, 40), point(7, 60), event_id="B"), "Red")
    train, test = split_by_start(spanning + later, cutoff=at(3))
    assert {r["event_id"] for r in train} == {"A"}
    assert {r["event_id"] for r in test} == {"B"}
