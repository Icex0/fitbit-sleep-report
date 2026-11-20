# Using an Apple Watch instead of a Fitbit

**Short answer:** partly. An Apple Watch records sleep stages, breathing rate, wrist temperature and
resting heart rate well enough for most of the sleep timing and quality findings in this report. Its
overnight blood oxygen and heart rate are too sparse for the oxygen-dip, heart-rate-cycle and
heart-rate-surge analyses, and its HRV is a different measure.

*Status: supported since October 2026 (Setup page, or `python -m sleep_report import-apple export.zip`). Tested on a
generated export built from real Fitbit nights; not yet on a real Apple Health export. Please report anything
that looks off.*

## Getting the data out

Apple has no cloud API like the Google Health API. Health data stays on the iPhone, and there are
two ways to get it:

- **Manual export:** in the Health app, open your profile, choose **Export All Health Data**, and share
  the resulting `export.zip`. It contains `export.xml` with every record. This would mean a manual
  export each time instead of the automatic download that Fitbit allows.
- **An iPhone app using HealthKit:** apps can read Health data with permission, which some
  third-party export apps do. This tool is a desktop program, so it would rely on the manual export or
  such an app.

## What carries over

| Data | Fitbit (this tool) | Apple Watch | Usable in this report |
|---|---|---|---|
| Sleep stages, timing, regularity | Yes | Yes: Core, Deep, REM, Awake | **Yes**: timing, regularity, duration, social jetlag, efficiency, stages |
| Breathing rate during sleep | Yes | Yes | **Yes** |
| Skin or wrist temperature | Yes | Yes, on newer models | **Yes** |
| Resting heart rate | Yes | Yes | **Yes** |
| Blood oxygen (SpO2) | Every minute during sleep | Collected opportunistically, with no fixed interval | **No**: too sparse to count oxygen dips per hour |
| Heart rate during sleep | About every 2 seconds | Typically every few minutes (users report 2-8 minutes) | **No**: too coarse for heart-rate cycles (CVHR) and surges |
| HRV | Nightly RMSSD | SDNN, a few readings a day | **No**: the Fitbit population norms are for RMSSD |

The watch decides when it measures blood oxygen and heart rate, and apps can't change the sampling
rate through HealthKit. Some third-party sleep apps run an overnight workout session to get heart
rate roughly every 5 seconds, at the cost of battery; that data could support the heart-rate
analyses, but it isn't what a standard Apple Watch records.

The report already handles missing data: findings without data simply don't appear.

## Apple's own sleep apnea notifications

Newer Apple Watches estimate **breathing disturbances** from wrist movement during sleep and can
notify you of possible moderate-to-severe sleep apnea. This feature is cleared by the FDA and is
better validated than the heart-rate-cycle method this report adapts for Fitbit.

- **How it decides:** it checks whether breathing disturbances are elevated on at least half of the
  nights in a 30-day window, and it stays silent with fewer than 10 nights of data.
- **Accuracy:** tuned to avoid false alarms. For moderate-to-severe apnea (AHI 15 or more) it
  detected about two thirds of cases, with 66.3% sensitivity in the FDA validation cohort and 66.6%
  in Apple's test set. False alarms in people without moderate-to-severe apnea were rare, with
  98.5% specificity in the FDA cohort and 95.9% in Apple's test set. The reference was a home sleep
  apnea test (Nox T3s).
- **Limits:** about a third of cases go unnoticed, and the FDA clearance states it is not intended to
  diagnose sleep apnea. Clinicians have pointed out that under-diagnosis is the bigger worry.

How breathing disturbances appear in `export.xml` (type name, units, frequency) couldn't be
confirmed from public documentation; a real export would show it.

## How the import works

[`sleep_report/sources/apple.py`](../sleep_report/sources/apple.py) reads the export as a stream (exports can be gigabytes):

- Sleep stages from the watch become nights and naps (the longest sleep in each 18:00-18:00 window is the
  night). iPhone "In bed" records and overlapping sleep from other apps are ignored.
- Blood oxygen (stored by Apple as a fraction) and heart rate are kept as they come; the report only counts
  oxygen dips with readings at least every 90 seconds and heart-rate surges or cycles with readings at least
  every 10 seconds, so sparse Apple data gets averages, never a falsely reassuring zero.
- Breathing rate, resting heart rate, SDNN and wrist temperature become nightly values; a wrist-temperature
  baseline is the median of the previous 30 nights.
- Breathing disturbances, if the export contains them, get their own literature finding with the validation
  figures above.

On a test export built from 77 real nights, the Apple import reproduced the Fitbit report's sleep timing,
regularity, duration, stages, breathing rate, average SpO2 and resting heart rate (within rounding).

## Sources

- [Apple developer forum: blood oxygen is collected opportunistically, without a fixed interval](https://developer.apple.com/forums/thread/713410)
- [Apple developer forum: heart-rate sampling frequency](https://developer.apple.com/forums/thread/701485)
- [Apple developer forum: HealthKit vital-sign update frequency](https://developer.apple.com/forums/thread/688901)
- [Apple developer forum: measuring HRV at short intervals](https://developer.apple.com/forums/thread/774136)
- [Sleep HRV: overnight RMSSD from an Apple Watch through a workout session](https://forum.intervals.icu/t/sleep-hrv-an-app-to-record-true-overnight-rmssd-hrv-from-the-apple-watch/111712)
- [Apple: Sleep Apnea Notifications on Apple Watch, September 2024 (validation)](https://apple.com/health/pdf/sleep-apnea/Sleep_Apnea_Notifications_on_Apple_Watch_September_2024.pdf)
- [FDA 510(k) K240929 summary](https://510k.innolitics.com/device/K240929)
- [Estimating breathing disturbances and sleep apnea risk from Apple Watch](https://fermatslibrary.com/s/estimating-breathing-disturbances-and-sleep-apnea-risk-from-apple-watch)
- [Tom's Guide: sleep apnea experts on the Apple Watch feature](https://www.tomsguide.com/wellness/sleep/sleep-apnea-experts-weigh-in-on-the-apple-watchs-latest-health-feature-heres-the-verdict)
- [Healio: advantages and pitfalls of sleep-monitoring apps and trackers](https://www.healio.com/news/pulmonology/20241015/qa-advantages-pitfalls-of-sleepmonitoring-apps-trackers)
- [Apple Health MCP: reads export.xml, including sleep stages, HRV (SDNN) and breathing rate](https://glama.ai/mcp/servers/w77ijud8aw)
- [Community analysis of an Apple Health export (sleep categories)](https://glama.ai/mcp/servers/@neiltron/apple-health-mcp/blob/3cf1edfd2f51b3b2717cfaaf72c8abe03862074d/apple_health_data_analysis.md)
