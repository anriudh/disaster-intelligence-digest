# M2 feature contract (draft for owner approval)

Status: **approved by the owner (2026-10-24), decisions D1–D5 in §8; checked against
`IMPLEMENTATION_PLAN.md` §4, `scorer.py` and `nlp.py` (§9). No code has changed.** Scope and label follow the approved M1 card
(`M1_DATA_CARD.md`): EONET Severe Storms only, label = GDACS TC `alertlevel`.

## 1. Scope of the builder

- The feature builder accepts only EONET events whose category is Severe Storms. For any other category it
  returns no feature vector, and the event's severity stays withheld under P-1.
- Inputs: the EONET event (geometry track and sources) and an **as-of time** `t`. GDACS data is never an
  input. GDACS is used only for the label.

## 2. As-of semantics

- Features at `t` use only the track points dated at or before `t`. A point after `t` must not change any
  feature value.
- **Production**: `t` = the date of the latest track point.
- **Training**: one row per track point of each labelled storm, `t` = that point's date. Every row of a storm
  carries the storm's final event-level `alertlevel`, so early rows ask "what will this storm's alert be?"
- Rows of one storm are correlated. Each row is weighted `1 / n_points` so every storm counts once. The split
  is by storm start date (M1 §4), so no storm has rows in both train and test.

## 3. Feature list (in this order)

| # | Feature | Definition | Missing |
|---|---|---|---|
| 1 | `wind_max_mph` | max `magnitudeValue` over points ≤ `t` where `magnitudeUnit` = `kts`, × 1.15078 | NaN if no such point |
| 2 | `wind_latest_mph` | `magnitudeValue` of the latest point ≤ `t` that has a `kts` value, × 1.15078 | NaN if no such point |
| 3 | `wind_trend_mph_per_day` | (`wind_latest_mph` − the wind at the latest `kts` point at least 24 h before it) / elapsed days | NaN if no such earlier point |
| 4 | `event_duration_days` | (`t` − date of the first track point) in days, as a float. A single point gives 0.0 | never missing |
| 5 | `source_count` | `len(eonet["sources"])` | never missing |
| 6 | `month` | month (1–12) of `t`, UTC | never missing |
| 7 | `latitude` | latitude of the latest point ≤ `t`, signed | never missing |
| 8 | `hemisphere` | 0 if `latitude` ≥ 0, else 1 | never missing |

Notes:
- **Units**: all 1,660 sampled points were `kts` (M1 §3a). A point with another unit or no value is skipped
  for features 1–3, and the builder counts how many it skipped.
- **`storm_category` is dropped** (this settles WS1.5). It would be a fixed step function of `wind_max_mph`,
  so a tree model gains nothing from it. If the UI wants a category, it can derive one from the wind for
  display.
- **`hemisphere` with `latitude`** is redundant for a tree model. It is kept only because it was in the
  previous list. The owner chose to keep it (D3).
- **`source_count` is not as-of**: EONET gives only the final source list, so in training it can count
  sources added after `t`. This is a small leak, kept and to be noted in the model card (D4).
- **Edge case fixed**: today's code (`orchestrator.py:72`) maps latitude 0 to South (`0 if lat > 0 else 1`).
  The contract puts 0 in the North.

## 4. Removed features (from the 17 in `train_model.py:13-31`)

| Feature | Reason |
|---|---|
| `gdacs_alert_score`, `gdacs_population_exposure` | leak the label (M1 §4) |
| `event_category_encoded`, `geometry_type_encoded` | constant for storms (all points) |
| `acres_burned`, `pct_contained`, `volcano_alert_encoded` | do not apply to storms |
| `wind_speed_mph`, `storm_category` (text-derived) | replaced by features 1–3 from the track; the storm text is the title only (M1 §3a) |
| `persons_affected`, `casualties`, `ner_location_count`, `ner_org_count` | storm text is the title only, so always missing or constant |

The NLP pipeline keeps running for summaries. Its output no longer feeds the scorer.

## 5. Missingness (P-2)

- Missing values are NaN and are passed to XGBoost as they are. There is no imputer, no medians and no
  sentinel values.
- The scorer records which features were missing (replacing the "imputed features" record from P-2).
  `gdacs_match_status` is still stored but is not a feature.

## 6. Compatibility

- The committed model (`backend/models/*.pkl`) expects the old 17 features and cannot score the new vector.
  Severity is already withheld from the API (A3). Until M3 trains a new model, the scorer is skipped for
  storms and records why. The pkl files are not touched in M2.
- At load time, the scorer checks that the model's feature names equal this list in this order, and refuses
  to score if they differ.

## 7. Tests M2 must add

1. The builder's output keys equal the contract list, in order. None of the removed features appear.
2. kts → mph conversion for a known value.
3. As-of: adding a later point with higher wind leaves every feature at an earlier `t` unchanged.
4. `wind_max_mph` is the max and `wind_latest_mph` is the latest, on a track whose peak is not the last point.
5. Trend: NaN with no point 24 h earlier; correct sign and value on a rising and on a falling track.
6. Duration: 0.0 for one point; correct for a multi-day track; uses the first point, not `t`.
7. Missing: a track with no `kts` values gives NaN for features 1–3, not 0 or −1. A non-`kts` point is skipped
   and counted.
8. Latitude 0 gives North; a negative latitude gives South.
9. A non-storm event gives no feature vector.
10. Training rows: a storm with k points gives k rows; row j uses only points 0..j; all rows share the label;
    the weights sum to 1 per storm; the split never puts one storm on both sides.
11. Scorer: refuses a model whose feature names differ from the contract; records missing features.

The single-feature separation check (no feature alone predicts the label) belongs to M4.

## 8. Owner decisions (2026-10-24)

- **D1 training rows**: one row per track point, weighted 1/n per storm (§2). Not chosen: one row per storm
  at its final point.
- **D2 wind trend**: kept (feature 3).
- **D3 hemisphere**: kept alongside `latitude`.
- **D4 `source_count`**: kept. The model card must note that in training it counts the final source list,
  including sources added after `t`.
- **D5 longitude**: not included, because it would stand in for the ocean basin and so for GDACS's exposure
  term.

## 9. Cross-check against the plan and the code (2026-10-24)

No conflict changes a feature or a decision above. Four points for M2 and M3:

1. **Plan items made moot by the scope.** `IMPLEMENTATION_PLAN.md` §4 lists units (WS1.5) and volcano
   encoding (WS1.3) under M2. WS1.5 is settled by the `kts` track (§3). The text regex `wind_speed_mph`
   (`nlp.py:28`) matches mph, knots and km/h without converting them, but it no longer feeds the scorer.
   WS1.3 does not apply, since volcanoes are not scored. Both stay open only if another category is scored
   later.
2. **M3's imputer item no longer applies.** The plan's M3 says to fit the imputer on the train split only.
   This contract uses no imputer (§5), so M3 drops that item and drops `imputer.pkl` from the new artifacts.
   The rest of M3 (versioned metadata, no artifact replacement before M4) is unchanged.
3. **One feature list.** `FEATURE_COLUMNS` is defined twice today, in `train_model.py:13-31` and in
   `scorer.py:33-39`. M2 keeps a single definition that the builder, the training script and the scorer all
   import. For the feature-name check in §6 to work, M3 must train on a DataFrame with these column names.
4. **Missing-feature record.** `score_event` returns `imputed_features` (`scorer.py:83`). Under §5 nothing is
   imputed, so the same list now means "missing". M2 keeps the existing key and storage so that no migration
   is needed, and documents its new meaning. Renaming it is left for later.
