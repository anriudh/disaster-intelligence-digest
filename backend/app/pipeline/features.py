"""
Storm feature builder, as specified in docs/audit/M2_FEATURE_CONTRACT.md.

Only Severe Storms are scored. Features are built "as of" a time t from the
EONET track points dated at or before t; GDACS is never an input.
"""
import logging
import math
from datetime import timedelta

from backend.app.pipeline.ingest import parse_date, point_of

logger = logging.getLogger(__name__)

SCORED_CATEGORY = "Severe Storms"
KTS_TO_MPH = 1.15078
TREND_WINDOW = timedelta(hours=24)

# The one feature list, shared by the builder, the training script and the scorer
FEATURE_COLUMNS = [
    "wind_max_mph",             # float, NaN without a kts point
    "wind_latest_mph",          # float, NaN without a kts point
    "wind_trend_mph_per_day",   # float, NaN without a kts point 24 h before the latest
    "event_duration_days",      # float, 0.0 for a single point
    "source_count",             # int, final source list (not as-of; see contract D4)
    "month",                    # int: 1-12, of t (UTC)
    "latitude",                 # float, latest point at or before t
    "hemisphere",               # int: North (latitude >= 0) = 0, South = 1
]

# GDACS alertlevel comes back as both "Green" and "GREEN"
LABEL_ENCODING = {"GREEN": 0, "ORANGE": 1, "RED": 2}

def label_from_alertlevel(alertlevel: str) -> int:
    return LABEL_ENCODING[alertlevel.upper()]

def track(eonet: dict) -> list:
    """The event's dated geometry points, oldest first."""
    points = [g for g in eonet.get("geometry") or [] if g.get("date")]
    return sorted(points, key=lambda g: parse_date(g["date"]))

def wind_mph(point: dict):
    """The point's wind in mph, or None unless it carries a kts magnitude."""
    if point.get("magnitudeUnit") != "kts" or point.get("magnitudeValue") is None:
        return None
    return float(point["magnitudeValue"]) * KTS_TO_MPH

def build_features(eonet: dict, as_of=None):
    """
    Returns the feature dict for a Severe Storm as of `as_of` (a datetime; the
    latest track point when None), or None for any other category.
    """
    if eonet["categories"][0]["title"] != SCORED_CATEGORY:
        return None

    points = track(eonet)
    if points:
        t = as_of if as_of is not None else parse_date(points[-1]["date"])
        points = [p for p in points if parse_date(p["date"]) <= t]
    if not points:
        raise ValueError(f"Event {eonet.get('id')} has no dated geometry at or before {as_of}")

    winds = [(parse_date(p["date"]), wind_mph(p)) for p in points]
    skipped = sum(1 for _, w in winds if w is None)
    if skipped:
        logger.warning(f"Event {eonet.get('id')}: {skipped} track point(s) without a kts wind skipped")
    winds = [(d, w) for d, w in winds if w is not None]

    wind_max = wind_latest = trend = math.nan
    if winds:
        wind_max = max(w for _, w in winds)
        latest_date, wind_latest = winds[-1]
        earlier = [(d, w) for d, w in winds if d <= latest_date - TREND_WINDOW]
        if earlier:
            earlier_date, earlier_wind = earlier[-1]
            trend = (wind_latest - earlier_wind) / ((latest_date - earlier_date).total_seconds() / 86400)

    latitude, _ = point_of(points[-1])
    return {
        "wind_max_mph": wind_max,
        "wind_latest_mph": wind_latest,
        "wind_trend_mph_per_day": trend,
        "event_duration_days": (t - parse_date(points[0]["date"])).total_seconds() / 86400,
        "source_count": len(eonet["sources"]),
        "month": t.month,
        "latitude": float(latitude),
        "hemisphere": 0 if latitude >= 0 else 1,
    }

def training_rows(eonet: dict, alertlevel: str) -> list:
    """
    One row per track point of a labelled storm, as of that point's date. Every
    row carries the storm's final label and a weight of 1/n, so each storm
    counts once; `start` is the storm's first point, used for the time split.
    """
    points = track(eonet)
    label = label_from_alertlevel(alertlevel)
    start = parse_date(points[0]["date"])
    return [
        {**build_features(eonet, as_of=parse_date(p["date"])),
         "label": label, "weight": 1 / len(points), "event_id": eonet["id"], "start": start}
        for p in points
    ]

def split_by_start(rows: list, cutoff):
    """Rows of storms that started before `cutoff` train; the rest test."""
    return [r for r in rows if r["start"] < cutoff], [r for r in rows if r["start"] >= cutoff]
