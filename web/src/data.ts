// Shapes of the files written by `python -m sleep_report export`, and loading them.

export type StageCode = "D" | "L" | "R" | "W" | "A" | "S";

export interface Recording {
  id: string;
  kind: "night" | "nap";
  night: string; // evening date, YYYY-MM-DD
  start: string; // local ISO time
  end: string;
  startH: number; // hours after 18:00 on the evening
  endH: number;
  breathing: number | null;
  sleep: null | {
    asleep: number;
    awake: number;
    efficiency: number | null;
    minutes: Partial<Record<string, number>>;
    deepPct: number | null;
    remPct: number | null;
    awakenings: number;
    toFallAsleep: number;
    awakeMid: number;
    afterWaking: number;
    segments: [number, number, StageCode][];
  };
  // dip and surge counts are null when the device's readings are too sparse to count them
  spo2: null | { avg: number; min: number; below90: number; odi3: number | null; odi4: number | null };
  hr: null | { median: number; lowest: number; surgesPerHour: number | null; surgesWithoutAwakening: number | null };
  hrv?: number | null; // Fitbit's nightly RMSSD, ms
  restingHr?: number | null;
  tempDev?: number | null; // skin temperature minus Fitbit's baseline, °C
  cvhr?: number | null; // apnea-like heart-rate cycles per hour in bed
  offNight?: boolean;
  offReasons?: string[];
  recovery?: Partial<Record<"hr" | "hrv" | "breathing" | "temp", { value: number; baseline: number; z: number; flagged: boolean }>>;
}

export interface Finding {
  id: string;
  topic: string;
  title: string;
  metric: string | null;
  value: number | null;
  valueText: string | null;
  valueLabel: string | null;
  repute: "good" | "attention" | "info";
  magnitude: number;
  headline: string;
  detail: string;
  background: string;
  reference: string | null; // the range this report's sources call good, for your age group
  bands: { range: string; repute: string; current: boolean }[];
  refs: string[];
  caveat: string;
  basedOn?: number | null; // nights of the data this finding rests on
  pending?: boolean; // too few nights yet: the headline says how many are needed
}

export interface Reference {
  id: string;
  authors: string;
  title: string;
  journal: string;
  year: number;
  citation?: string;
  pmid?: string;
  doi?: string;
  url?: string;
}

export interface Profile {
  age: number | null;
  group: "teen" | "young_adult" | "adult" | "older";
  groupLabel: string;
  ageAssumed: boolean;
  daysOff: string[];
  usualBedtime: string;
  shiftWork: boolean;
  oftenTired: boolean | null;
  source?: "google" | "apple";
}

export const SOURCE_LABEL = { google: "Fitbit via Google Health API", apple: "Apple Watch via Apple Health export" } as const;

export interface Summary {
  generated: string;
  profile: Profile | null;
  metrics: Record<string, number | string | null | Record<string, number>>;
  recordings: Recording[];
  findings: Finding[];
  references: Reference[];
  minNights?: number; // the literature report needs this many nights
}

export interface NightDetail {
  id: string;
  start: string;
  end: string;
  stages: [number, number, StageCode][]; // seconds after start
  short: [number, number][];
  spo2: [number, number][];
  settling: number[];
  dips: [number, number, number, number][]; // start, end, nadir, baseline
  hr: [number, number][];
  surges: [number, number][]; // time, peak bpm
  cvhr?: number[]; // seconds of apnea-like heart-rate cycle dips
}

let summaryPromise: Promise<Summary> | null = null;
const nightCache = new Map<string, Promise<NightDetail>>();

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export function loadSummary(): Promise<Summary> {
  summaryPromise ??= getJson<Summary>(`data/summary.json?t=${Date.now()}`);
  return summaryPromise;
}

/** Forget cached data, after the report was rebuilt. */
export function clearCache() {
  summaryPromise = null;
  nightCache.clear();
}

export function loadNight(id: string): Promise<NightDetail> {
  let p = nightCache.get(id);
  if (!p) {
    p = getJson<NightDetail>(`data/nights/${id}.json?t=${Date.now()}`);
    nightCache.set(id, p);
  }
  return p;
}

export const STAGES: { code: StageCode; label: string; color: string; row: number }[] = [
  { code: "W", label: "Awake", color: "var(--stage-wake)", row: 0 },
  { code: "R", label: "REM", color: "var(--stage-rem)", row: 1 },
  { code: "L", label: "Light", color: "var(--stage-light)", row: 2 },
  { code: "D", label: "Deep", color: "var(--stage-deep)", row: 3 },
  { code: "A", label: "Asleep", color: "var(--stage-light)", row: 2 },
  { code: "S", label: "Restless", color: "var(--stage-restless)", row: 1 },
];
export const stageOf = (code: StageCode) => STAGES.find((s) => s.code === code) ?? STAGES[2];
