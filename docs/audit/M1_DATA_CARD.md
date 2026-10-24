# M1 data card

Status: **approved by the owner, 2026-10-24.** The owner chose a storms-only, GDACS-labelled
model (option (a), 2026-10-24). Evidence: desk research plus a read-only sample (§7: 16 API calls and 2
licence pages, raw outputs kept outside the repository). Items still marked *unverified* could not be
settled by that sample.

## 1. What the label has to mean

The model emits GREEN/ORANGE/RED (shown as LOW/MODERATE/HIGH, `scorer.py` `LABEL_MAP`). That is GDACS's
alert scale, so the label policy (argmax of 3 classes) stays as it is; M1 only decides **where real labels
come from**. The committed model was trained on synthetic labels (LEDGER F1, T2-2).

## 2. Candidate sources

| Source | Label it gives | Categories | Years | Licence | Join to EONET | Verdict |
|---|---|---|---|---|---|---|
| **GDACS alerts** (`gdacsapi/api/events/geteventlist/SEARCH`: `eventlist`, `alertlevel`, `fromdate`/`todate`, 100 per page, newest first, no total count) | Green/Orange/Red, same scale as the model | EQ, TC, FL from 2016 or earlier; VO in 2020 and 2024 but not 2016; WF in 2024 only (none returned for 2016 or 2020) | see §7 | EC/JRC reuse with acknowledgement; GDACS terms disclaim accuracy (automatic alerts not reviewed by experts); no explicit data licence found | `match_events` distance/date rule. The exact route through GDACS-sourced EONET events does not exist for recent years (0 of 1,629 closed 2024 events) | **Usable as the label for Severe Storms only** (§5) |
| **USGS PAGER** | Green/Yellow/Orange/Red from estimated fatalities and losses | Earthquakes only | per-event in ComCat; bulk history *unverified* | US government, public domain | EONET carried no earthquakes in 2024 (§7) | Not useful while EONET carries no earthquakes |
| **ICS-209-PLUS** (St. Denis et al. 2023, *Scientific Data* 10:112) | No alert level; observed impact (structures destroyed, fatalities, cost, size) from which a label rule would have to be defined | US incidents, about 34,000 wildfires | 1999–2020 | *unverified*: figshare and Ag Data Commons both refused automated access (403) | IRWIN incidents by name/date/location; no shared ID with EONET found | The only labelled source found for US wildfires, which are 92% of EONET's closed 2024 events; ends in 2020 and covers only the largest 1–2% of fires |
| **EM-DAT** (CRED) | No alert level; deaths, affected, damages | All, global, events above EM-DAT's entry thresholds | 1900– | free only for academic, non-profit research, international public bodies and media; any other user is commercial and needs a paid licence; no redistribution, no derivative databases, no internet sharing to unauthorised users | GLIDE / country / date; no shared ID | Evaluation only, and only if the owner qualifies as a free user; can never be committed to the repo |

## 3. Label definition (storms-only scope)

- **Scope**: EONET Severe Storms only. Wildfires, Volcanoes, Floods and Earthquakes are not scored; their
  severity stays withheld under P-1.
- **Label** = the GDACS TC event's `alertlevel`, upper-cased before mapping (the API returns both `Green` and
  `GREEN`, `Orange` and `ORANGE`), mapped GREEN→0, ORANGE→1, RED→2 as now.
- **Rows** = closed EONET Severe Storms that `match_events` joins to a GDACS TC event. Unjoined storms are
  excluded from training (they have no label), and their share is reported (61% in 2024).
- **What this label is**: GDACS's automatic estimate of humanitarian impact (wind intensity × exposed
  population × vulnerability), not observed harm. The UI and model card must say so.
- **Size**: about 33 labelled storms per year, roughly 30% ORANGE or RED. The number of usable years depends
  on how far back EONET's closed storm history goes (*unverified*); M4's metrics will be coarse at this size.

## 3a. Inputs available for storms (measured on the 85 closed 2024 storms)

- Every EONET storm geometry point carries `magnitudeValue` with `magnitudeUnit` = `kts` (1,660 of 1,660
  points; 2–65 points per storm, median 17). This is a structured wind track.
- No storm has a description, and T3-1 found JTWC sources unextractable, so the scraped text is the title
  alone ("Tropical Cyclone Chido"). Text-derived features (`wind_speed_mph`, `storm_category`,
  `persons_affected`, `casualties`, NER counts) will be missing or constant.

## 4. Leakage review

| Risk | Finding | Required action |
|---|---|---|
| GDACS score as feature and label | `gdacs_alert_score` is the number GDACS thresholds into `alertlevel`; `gdacs_population_exposure` is a direct input to it. Both are in the 17 features (`train_model.py:13-31`) | **Remove both from the feature set** (an M2 change). A single-feature separation check in M4 must confirm no remaining feature alone predicts the label |
| Label only exists when GDACS matched | Training rows are all matched events, so `gdacs_match_status` is constant in training and uninformative in production | Do not use match status as a feature; report the matched share |
| Same hazard inputs as GDACS | Wind speed and storm category are GDACS TC inputs too | Legitimate signal, not leakage; keep, but say the model partly re-derives GDACS |
| Final versus as-of label | GDACS alert can rise across episodes (`episodealertlevel` vs `alertlevel`); features use the latest EONET state | Use the event-level `alertlevel`; build features as of each event's last EONET update; note the mismatch in the model card |
| Time | Random splits mix seasons and storms that share episodes | Split by event start date (train on earlier years, test on later) |
| Synthetic legacy | The committed imputer medians come from synthetic data (LEDGER T2-2) | Refit everything on real rows only (M3) |

## 5. Coverage per category (measured, §7)

| Category | EONET closed 2024 | GDACS label available | Joined (`match_events`) | GDACS class mix in sample |
|---|---|---|---|---|
| Wildfires | 1,501 (IRWIN 1,497, InciWeb 4) | WF only from about 2024, mostly outside the US (T3-2) | 0, but the WF page covered only 20–31 Dec 2024 | 100 Green |
| Severe Storms | 85 (JTWC 65, NOAA NHC 12) | TC, complete for 2024 (92 events, page not full) | **33 of 85 (39%)** | 2024: 64 Green, 17 Orange, 11 Red |
| Volcanoes | 43 (Smithsonian 39) | VO, 22 events in 2024 | 2 | 2024: 20 Green, 2 Orange |
| Floods | **0** | FL from 2016 | none to join | 2024 page (Sep–Dec): 97 Green, 2 Orange, 1 Red |
| Earthquakes | **0** | EQ from 2016 | none to join | one week per year: almost all Green |

What this means:
- **Severe Storms** is the only category with both joinable events and a usable class mix: about 33
  labelled storms per year, roughly 30% Orange or Red.
- **Wildfires**, nearly all of EONET's events, get almost no GDACS labels. Labelling them needs
  ICS-209-PLUS (ends 2020, licence unverified) or another US source.
- **Floods and Earthquakes** do not appear in EONET's 2024 events at all, so the model's FL and EQ classes
  cannot be trained or tested from this pipeline.
- **Volcanoes** give about 2 labelled events per year.

## 6. Owner decisions

1. **Scope: decided**, storms-only GDACS-labelled model (option (a), 2026-10-24). Not chosen: ICS-209-PLUS
   for wildfires (b), stopping Track M (c).
2. **Label meaning: accepted** with the scope: a GDACS-style alert, not observed impact.
3. Removing `gdacs_alert_score` and `gdacs_population_exposure` from the features is required by §4 and
   is carried into M2's feature contract for approval there.
4. EM-DAT: not needed for the storms-only scope; open only if wanted for evaluation (requires being a free
   user: academic, non-profit research, international public body or media).

## 7. Read-only sample (run 2026-10-24)

Outputs outside the repository; network off for the analysis, which used the branch's `match_events`.

- **GDACS** `geteventlist/SEARCH`, one page (100) per type for 2016, 2020 and 2024, all alert levels: 15
  calls. 12 returned events; VO 2016, WF 2016 and WF 2020 returned 204 (no content). Results come newest
  first with no total, so a full page covers only the end of the year: EQ about one week, WF 2024 about
  eleven days, FL about one quarter. TC and VO pages were not full, so those years are complete.
- **EONET** closed events, 2024, five allowed categories: 1 call, 1,629 events (Wildfires 1,501, Severe
  Storms 85, Volcanoes 43). None has a GDACS source.
- **Licence pages**: EM-DAT terms read; ICS-209-PLUS pages refused automated access (403).

Not settled: how far back EONET's closed history goes (and so the total number of labelled storms), the
ICS-209-PLUS licence, and the full-year class mix for EQ, FL and WF (it would need paging through every
result).

## Sources

- GDACS API quickstart: https://data.gdacs.org/Documents/2025/GDACS_API_quickstart_v1.pdf
- OCHA lens GDACS client (pagination, coverage notes): https://ocha-lens.readthedocs.io/en/latest/_modules/ocha_lens/datasources/gdacs.html
- GDACS terms of use: https://gdacs.org/About/termofuse.aspx
- EC reuse notice: https://data.jrc.ec.europa.eu/licence/com_reuse
- GDACS earthquake alert model: https://gdacs.org/Knowledge/models_EQ.aspx
- USGS PAGER background: https://earthquake.usgs.gov/data/pager/background.php
- LossPAGER product: https://ghsc.code-pages.usgs.gov/hazdev/pdl/userguide/products/known-types/losspager.html
- ICS-209-PLUS: https://figshare.com/articles/dataset/ICS209-PLUS_Cleaned_databases/8048252
- EM-DAT terms of use: https://doc.emdat.be/docs/legal/terms-of-use/
