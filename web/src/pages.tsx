import { Fragment, useEffect, useMemo, useState } from "react";
import { loadNight, type Finding, type NightDetail, type Profile, type Recording, type Reference, type Summary } from "./data";
import { calendar, NightPanels, SleepDiary, StageLegend, TrendChart } from "./charts";
import { clockAt, dayLabel, duration, fixed, longDate, timeOf } from "./format";
import { Flag, Pips, go } from "./ui";

const nightsOf = (s: Summary) => s.recordings.filter((r) => r.kind === "night");
const pct = (v: number) => `${v.toFixed(0)}%`;
const h1 = (v: number) => `${v.toFixed(1)} h`;

/* ------------------------------------------------------------------ citations */

function useRefNumbers(refs: Reference[]) {
  return useMemo(() => new Map(refs.map((r, i) => [r.id, i + 1])), [refs]);
}

function Cites({ ids, numbers }: { ids: string[]; numbers: Map<string, number> }) {
  return (
    <>
      {ids.map((id) => (
        <a
          key={id}
          className="cite"
          href={`#/literature`}
          onClick={(e) => {
            e.preventDefault();
            const el = document.getElementById(`ref-${id}`);
            if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
            else go("literature");
          }}
        >
          [{numbers.get(id) ?? "?"}]
        </a>
      ))}
    </>
  );
}

/* ------------------------------------------------------------------ profile */

/** Which reference ranges were used, and how to change them. */
// Shown instead of the literature results while there are too few nights to say what's typical.
function NoFindings({ data }: { data: Summary }) {
  const nights = nightsOf(data).length;
  const min = data.minNights ?? 0;
  if (nights < min) {
    return (
      <p className="lede">
        The comparison with the literature needs at least {min} nights, so it can say what's typical for you rather than describe one night. You
        have {nights} so far: {min - nights} more to go. The nights you have are already in the sleep diary and the night pages.
      </p>
    );
  }
  return <p className="lede">No literature findings yet. Run <code>python -m sleep_report export</code> after adding the knowledge base.</p>;
}

function ProfileNote({ profile }: { profile: Profile | null }) {
  if (!profile) return null;
  const days = profile.daysOff.length ? profile.daysOff.join(", ") : "none";
  return (
    <p className="small profile-note">
      Reference ranges for <b>{profile.groupLabel}</b>
      {profile.ageAssumed ? " (age not set)" : ` (age ${profile.age})`} · days off {days} · usual bedtime {profile.usualBedtime}
      {profile.shiftWork ? " · shift work" : ""}. <a href="#/setup">{profile.ageAssumed ? "Set your age and schedule" : "Change"}</a> on the Setup page.
    </p>
  );
}

/* ------------------------------------------------------------------ overview */

export function Overview({ data }: { data: Summary }) {
  const nights = nightsOf(data);
  const days = calendar(nights[0].night, nights[nights.length - 1].night);
  const measured = data.findings.filter((f) => f.metric);
  const topics = [...new Set(measured.map((f) => f.topic))];
  const attention = data.findings.filter((f) => f.repute === "attention").length;
  const hasStages = nights.some((r) => r.sleep);

  return (
    <div className="page">
      <section className="section">
        <div className="section-head">
          <h2>Results</h2>
          <span className="label">Your values against published reference values</span>
        </div>
        {measured.length === 0 ? (
          <NoFindings data={data} />
        ) : (
          <>
            <p className="lede">
              {measured.length} measures from {nights.length} nights, each compared with the reference from the literature.{" "}
              {attention > 0 ? `${attention} need${attention === 1 ? "s" : ""} attention.` : "None are outside the reference."}{" "}
              <a href="#/literature">Read the literature report</a> for the evidence behind each line.
            </p>
            <ProfileNote profile={data.profile} />
            <div className="table-scroll">
              <table className="results">
                <thead>
                  <tr>
                    <th scope="col">Measure</th>
                    <th scope="col">Result</th>
                    <th scope="col">Reference</th>
                    <th scope="col">Flag</th>
                    <th scope="col">Note</th>
                  </tr>
                </thead>
                <tbody>
                  {topics.map((topic) => (
                    <Fragment key={topic}>
                      <tr className="group">
                        <td colSpan={5}>{topic}</td>
                      </tr>
                      {measured
                        .filter((f) => f.topic === topic)
                        .map((f) => (
                          <tr key={f.id}>
                            <th scope="row">{f.valueLabel ?? f.title}</th>
                            <td className="value">{f.valueText}</td>
                            <td className="ref">{f.reference ?? "–"}</td>
                            <td><Flag repute={f.repute} /></td>
                            <td className="note">{f.headline}</td>
                          </tr>
                        ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Sleep diary</h2>
          <span className="label">Each row is one night, 18:00 to 18:00</span>
        </div>
        <StageLegend withNoData={nights.some((r) => !r.sleep)} />
        <SleepDiary recs={data.recordings} days={days} />
        <p className="small" style={{ marginTop: 8 }}>
          Naps are drawn on the row of the night they precede. Rules mark the start of each week. Click a row to open that night.
        </p>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Night by night</h2>
          <a className="small" href="#/nights">All values as a table</a>
        </div>
        <div className="multiples">
          {hasStages && (
            <div className="wide">
              <TrendChart
                title="Time asleep, by stage"
                unit="hours"
                days={days}
                recs={nights}
                stacked
                yDomain={[0, 12]}
                yFormat={(v) => `${v}`}
                refLine={{ value: 7, label: "7 h" }}
                series={[
                  { key: "deep", label: "Deep", color: "var(--stage-deep)", kind: "column", value: (r) => (r.sleep ? (r.sleep.minutes.DEEP ?? 0) / 60 : null), format: h1 },
                  { key: "light", label: "Light", color: "var(--stage-light)", kind: "column", value: (r) => (r.sleep ? ((r.sleep.minutes.LIGHT ?? 0) + (r.sleep.minutes.ASLEEP ?? 0)) / 60 : null), format: h1 },
                  { key: "rem", label: "REM", color: "var(--stage-rem)", kind: "column", value: (r) => (r.sleep ? (r.sleep.minutes.REM ?? 0) / 60 : null), format: h1 },
                ]}
                height={220}
              />
            </div>
          )}
          <TrendChart
            title="Oxygen dips per hour"
            unit="ODI, events per hour"
            days={days}
            recs={nights}
            refLine={{ value: 5, label: "5 per hour" }}
            series={[
              { key: "odi3", label: "Dips ≥ 3%", color: "var(--series-1)", kind: "column", value: (r) => r.spo2?.odi3 ?? null, format: (v) => v.toFixed(1) },
              { key: "odi4", label: "Dips ≥ 4%", color: "var(--event)", kind: "dot", value: (r) => r.spo2?.odi4 ?? null, format: (v) => v.toFixed(1) },
            ]}
          />
          <TrendChart
            title="Blood oxygen"
            unit="SpO₂ %"
            days={days}
            recs={nights}
            yDomain={[82, 100]}
            refLine={{ value: 90, label: "90%" }}
            series={[
              { key: "avg", label: "Night average", color: "var(--series-1)", kind: "line", value: (r) => r.spo2?.avg ?? null, format: (v) => `${v.toFixed(1)}%` },
              { key: "min", label: "Night minimum", color: "var(--event)", kind: "dot", value: (r) => r.spo2?.min ?? null, format: (v) => `${v.toFixed(1)}%` },
            ]}
          />
          <TrendChart
            title="Heart rate asleep"
            unit="beats per minute"
            days={days}
            recs={nights}
            yDomain={[40, 90]}
            series={[
              { key: "hr", label: "Median", color: "var(--series-1)", kind: "line", value: (r) => r.hr?.median ?? null, format: (v) => `${v} bpm` },
              { key: "low", label: "Lowest minute", color: "var(--event)", kind: "dot", value: (r) => r.hr?.lowest ?? null, format: (v) => `${v} bpm` },
            ]}
          />
          <TrendChart
            title="Heart-rate surges"
            unit="per hour asleep"
            days={days}
            recs={nights}
            series={[
              { key: "surges", label: "All surges ≥ 10 bpm", color: "var(--series-1)", kind: "column", value: (r) => r.hr?.surgesPerHour ?? null, format: (v) => v.toFixed(1) },
              { key: "silent", label: "Without a detected awakening", color: "var(--event)", kind: "dot", value: (r) => r.hr?.surgesWithoutAwakening ?? null, format: (v) => v.toFixed(1) },
            ]}
          />
          <TrendChart
            title="Apnea-like heart-rate cycles"
            unit="per hour in bed"
            days={days}
            recs={nights}
            refLine={{ value: 11, label: "11 (watch)" }}
            series={[{ key: "cvhr", label: "Cycles", color: "var(--series-1)", kind: "column", value: (r) => r.cvhr ?? null, format: (v) => `${v.toFixed(1)} per hour` }]}
            note="Not validated on Fitbit data; the literature report explains the cut-off and how much of this count is noise."
          />
          <TrendChart
            title="Heart-rate variability during sleep"
            unit={data.metrics.hrv_kind === "sdnn" ? "SDNN, ms" : "RMSSD, ms"}
            days={days}
            recs={nights}
            series={[
              { key: "hrv", label: "HRV", color: "var(--series-1)", kind: "line", value: (r) => r.hrv ?? null, format: (v) => `${v.toFixed(1)} ms` },
              { key: "off", label: "Off night", color: "var(--event)", kind: "dot", value: (r) => (r.offNight ? r.hrv ?? null : null), format: () => "off night" },
            ]}
            note="Off nights: at least two of heart rate, HRV, breathing rate and skin temperature clearly away from your previous four weeks."
          />
          <TrendChart
            title="Breathing rate"
            unit="breaths per minute"
            days={days}
            recs={nights}
            yDomain={[8, 24]}
            refBand={{ from: 12, to: 20, label: "usual 12–20" }}
            series={[{ key: "br", label: "Breathing rate", color: "var(--series-1)", kind: "line", value: (r) => r.breathing, format: (v) => `${v.toFixed(1)} /min` }]}
          />
        </div>
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ nights table */

type Col = { key: string; label: string; get: (r: Recording) => number | string | null; show: (r: Recording) => string; num?: boolean };

const COLUMNS: Col[] = [
  { key: "night", label: "Night", get: (r) => r.start, show: (r) => (r.kind === "nap" ? `Nap ${dayLabel(r.start.slice(0, 10))}` : dayLabel(r.night)) },
  { key: "bed", label: "Bed", get: (r) => r.startH, show: (r) => timeOf(r.start), num: true },
  { key: "up", label: "Up", get: (r) => r.endH, show: (r) => timeOf(r.end), num: true },
  { key: "asleep", label: "Asleep", get: (r) => r.sleep?.asleep ?? null, show: (r) => (r.sleep ? h1(r.sleep.asleep / 60) : "–"), num: true },
  { key: "eff", label: "Eff.", get: (r) => r.sleep?.efficiency ?? null, show: (r) => (r.sleep?.efficiency != null ? pct(r.sleep.efficiency) : "–"), num: true },
  { key: "deep", label: "Deep", get: (r) => r.sleep?.deepPct ?? null, show: (r) => (r.sleep?.deepPct != null ? pct(r.sleep.deepPct) : "–"), num: true },
  { key: "rem", label: "REM", get: (r) => r.sleep?.remPct ?? null, show: (r) => (r.sleep?.remPct != null ? pct(r.sleep.remPct) : "–"), num: true },
  { key: "wakes", label: "Wakes", get: (r) => r.sleep?.awakenings ?? null, show: (r) => (r.sleep ? String(r.sleep.awakenings) : "–"), num: true },
  { key: "spo2", label: "SpO₂", get: (r) => r.spo2?.avg ?? null, show: (r) => (r.spo2 ? `${fixed(r.spo2.avg)}%` : "–"), num: true },
  { key: "min", label: "Min", get: (r) => r.spo2?.min ?? null, show: (r) => (r.spo2 ? `${fixed(r.spo2.min)}%` : "–"), num: true },
  { key: "odi", label: "ODI 3%", get: (r) => r.spo2?.odi3 ?? null, show: (r) => fixed(r.spo2?.odi3), num: true },
  { key: "hr", label: "HR", get: (r) => r.hr?.median ?? null, show: (r) => (r.hr ? String(r.hr.median) : "–"), num: true },
  { key: "surges", label: "Surges/h", get: (r) => r.hr?.surgesPerHour ?? null, show: (r) => fixed(r.hr?.surgesPerHour), num: true },
  { key: "br", label: "Breathing", get: (r) => r.breathing, show: (r) => fixed(r.breathing), num: true },
  { key: "hrv", label: "HRV", get: (r) => r.hrv ?? null, show: (r) => fixed(r.hrv), num: true },
  { key: "cvhr", label: "HR cycles/h", get: (r) => r.cvhr ?? null, show: (r) => fixed(r.cvhr), num: true },
  { key: "off", label: "Off night", get: (r) => (r.offNight ? 1 : 0), show: (r) => (r.offNight ? "yes" : "") },
];

export function NightsTable({ data }: { data: Summary }) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "night", dir: -1 });
  const [naps, setNaps] = useState(true);
  const col = COLUMNS.find((c) => c.key === sort.key)!;
  const rows = data.recordings
    .filter((r) => naps || r.kind === "night")
    .slice()
    .sort((a, b) => {
      const va = col.get(a);
      const vb = col.get(b);
      if (va == null) return 1;
      if (vb == null) return -1;
      return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
    });
  return (
    <div className="page">
      <section className="section">
        <div className="section-head">
          <h2>Nights</h2>
          <label className="small">
            <input type="checkbox" checked={naps} onChange={(e) => setNaps(e.target.checked)} /> Include naps
          </label>
        </div>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th key={c.key} scope="col">
                    <button
                      aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : undefined}
                      onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? ((-s.dir) as 1 | -1) : c.num ? -1 : 1 }))}
                    >
                      {c.label}
                      {sort.key === c.key ? (sort.dir === 1 ? " ↑" : " ↓") : ""}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={r.kind} onClick={() => go(`night/${r.id}`)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && go(`night/${r.id}`)}>
                  {COLUMNS.map((c) => (
                    <td key={c.key}>{c.show(r)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ one night */

export function NightPage({ data, id }: { data: Summary; id: string }) {
  const [night, setNight] = useState<NightDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const index = data.recordings.findIndex((r) => r.id === id);
  const rec = data.recordings[index];
  useEffect(() => {
    let live = true;
    setError(null);
    loadNight(id).then((n) => live && setNight(n), (e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [id]);
  if (!rec) return <p className="lede section">Unknown night. <a href="#/nights">Back to all nights</a></p>;
  const prev = data.recordings[index - 1];
  const next = data.recordings[index + 1];
  const s = rec.sleep;
  const label = rec.kind === "night" ? `Night of ${longDate(rec.night)}` : `Nap on ${longDate(rec.start.slice(0, 10))}`;
  const figures: [string, string, string?][] = [];
  if (s) {
    figures.push(["Asleep", duration(s.asleep), `${s.awake} min awake in bed`]);
    figures.push(["Efficiency", s.efficiency != null ? pct(s.efficiency) : "–", `${s.toFallAsleep} min to fall asleep`]);
    if (s.deepPct != null) figures.push(["Deep sleep", pct(s.deepPct), "of time asleep"]);
    if (s.remPct != null) figures.push(["REM sleep", pct(s.remPct), "of time asleep"]);
    figures.push(["Woke up", `${s.awakenings}×`, "incl. brief awakenings"]);
  }
  if (rec.spo2) figures.push(["Blood oxygen", `${fixed(rec.spo2.avg)}%`, `lowest ${fixed(rec.spo2.min)}%${rec.spo2.odi3 != null ? ` · ODI ${fixed(rec.spo2.odi3)}/h` : ""}`]);
  if (rec.hr) figures.push(["Heart rate", `${rec.hr.median} bpm`, rec.hr.surgesPerHour != null ? `${fixed(rec.hr.surgesPerHour)} surges per hour` : `lowest ${rec.hr.lowest}`]);
  if (rec.breathing != null) figures.push(["Breathing", `${fixed(rec.breathing)}`, "breaths per minute"]);
  if (rec.hrv != null) figures.push(["HRV", `${fixed(rec.hrv)} ms`, rec.restingHr != null ? `resting HR ${rec.restingHr}` : "RMSSD"]);

  const events: { t: number; text: string }[] = night
    ? [
        ...night.dips.map(([a, , nadir, base]) => ({ t: a, text: `Oxygen dip to ${nadir.toFixed(1)}% (from ${base.toFixed(1)}%)` })),
        ...night.surges.map(([t, peak]) => ({ t, text: `Heart-rate surge to ${peak} bpm` })),
        ...cvhrRuns(night.cvhr ?? []).map(([a, b, n]) => ({ t: a, text: `${n} apnea-like heart-rate cycles until ${clockAt(night.start, b)}` })),
        ...night.stages
          .filter(([a, b, c]) => c === "W" && b - a >= 600)
          .map(([a, b]) => ({ t: a, text: `Awake for ${Math.round((b - a) / 60)} min` })),
      ].sort((p, q) => p.t - q.t)
    : [];

  return (
    <div className={`page ${night ? "" : "loading-hold"}`}>
      <nav className="night-nav" aria-label="Other nights">
        {prev ? <a href={`#/night/${prev.id}`}>← {prev.kind === "nap" ? "Nap" : dayLabel(prev.night)}</a> : <span />}
        <a href="#/nights">All nights</a>
        {next ? <a href={`#/night/${next.id}`}>{next.kind === "nap" ? "Nap" : dayLabel(next.night)} →</a> : <span />}
      </nav>
      <header className="night-head">
        <h2>{label}</h2>
        <p className="when">
          {timeOf(rec.start)} to {timeOf(rec.end)} · {duration(Math.round((rec.endH - rec.startH) * 60))} in bed
        </p>
      </header>
      {figures.length > 0 && (
        <div className="figures section" style={{ marginTop: 20 }}>
          {figures.map(([l, v, sub]) => (
            <div className="figure" key={l}>
              <div className="f-label">{l}</div>
              <div className="f-value">{v}</div>
              {sub && <div className="f-sub">{sub}</div>}
            </div>
          ))}
        </div>
      )}
      {rec.offNight && <OffNightNote rec={rec} />}
      <section className="section">
        <div className="legend">
          <StageLegendInline />
          <span className="key"><i className="linekey" style={{ background: "var(--series-1)" }} />SpO₂ and heart rate</span>
          <span className="key"><i className="swatch" style={{ background: "var(--event)", opacity: 0.35 }} />Oxygen dip ≥ 3%</span>
          <span className="key"><i className="tri" />Heart-rate surge ≥ 10 bpm</span>
          <span className="key"><i className="swatch" style={{ background: "var(--stage-rem)", width: 3, height: 12, borderRadius: 0 }} />Apnea-like heart-rate cycle</span>
          <span className="key"><i className="swatch" style={{ background: "var(--muted)", borderRadius: 5, width: 8, height: 8 }} />Sensor settling (not counted)</span>
        </div>
        {error && <p className="lede">Couldn't load this night: {error}</p>}
        {night && <NightPanels night={night} />}
      </section>
      {night && (
        <section className="section">
          <div className="section-head">
            <h2>Events</h2>
            <span className="label">{events.length} in this {rec.kind}</span>
          </div>
          {events.length === 0 ? (
            <p className="small">No oxygen dips, heart-rate surges or long awake periods.</p>
          ) : (
            <ul className="events">
              {events.map((e, i) => (
                <li key={i}>
                  <span className="t">{clockAt(night.start, e.t)}</span>
                  <span>{e.text}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

/** Group cycle dips into runs (dips no more than 130 s apart): [start, end, count]. */
function cvhrRuns(dips: number[]): [number, number, number][] {
  const runs: [number, number, number][] = [];
  dips.forEach((t, i) => {
    if (i && t - dips[i - 1] <= 130) {
      const last = runs[runs.length - 1];
      last[1] = t;
      last[2] += 1;
    } else runs.push([t, t, 1]);
  });
  return runs;
}

const SIGNAL_LABEL = { hr: "Heart rate asleep", hrv: "HRV", breathing: "Breathing rate", temp: "Skin temperature vs baseline" } as const;
const SIGNAL_UNIT = { hr: " bpm", hrv: " ms", breathing: "/min", temp: " °C" } as const;

function OffNightNote({ rec }: { rec: Recording }) {
  const rows = Object.entries(rec.recovery ?? {}) as [keyof typeof SIGNAL_LABEL, { value: number; baseline: number; z: number; flagged: boolean }][];
  return (
    <section className="section off-night">
      <div className="section-head">
        <h2>An off night</h2>
        <span className="label">{(rec.offReasons ?? []).join(" · ")}</span>
      </div>
      <p className="lede">
        Compared with your previous four weeks, several signals moved the way illness, alcohol or strain push them.{" "}
        <a href="#/literature">The literature report</a> explains what each pattern usually means.
      </p>
      <table className="results">
        <thead>
          <tr><th scope="col">Signal</th><th scope="col">This night</th><th scope="col">Your normal</th><th scope="col">Flag</th></tr>
        </thead>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <th scope="row">{SIGNAL_LABEL[k]}</th>
              <td className="value">{k === "temp" && v.value > 0 ? "+" : ""}{v.value.toFixed(k === "hr" ? 0 : k === "temp" ? 2 : 1)}{SIGNAL_UNIT[k]}</td>
              <td className="ref">{k === "temp" && v.baseline > 0 ? "+" : ""}{v.baseline.toFixed(k === "hr" ? 0 : k === "temp" ? 2 : 1)}{SIGNAL_UNIT[k]}</td>
              <td>{v.flagged ? <Flag repute="attention" label="Clearly off" /> : <Flag repute="info" label="Within normal" />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function StageLegendInline() {
  return (
    <>
      {[
        ["Deep", "var(--stage-deep)"],
        ["Light", "var(--stage-light)"],
        ["REM", "var(--stage-rem)"],
        ["Awake", "var(--stage-wake)"],
      ].map(([l, c]) => (
        <span className="key" key={l}>
          <i className="swatch" style={{ background: c }} />
          {l}
        </span>
      ))}
    </>
  );
}

/* ------------------------------------------------------------------ literature */

type ReputeFilter = "all" | "attention" | "good" | "info";

export function Literature({ data }: { data: Summary }) {
  const [filter, setFilter] = useState<ReputeFilter>("all");
  const [order, setOrder] = useState<"magnitude" | "topic">("magnitude");
  const numbers = useRefNumbers(data.references);
  const counts = { attention: 0, good: 0, info: 0 } as Record<string, number>;
  data.findings.forEach((f) => counts[f.repute]++);
  let shown = data.findings.filter((f) => filter === "all" || f.repute === filter);
  if (order === "topic") shown = shown.slice().sort((a, b) => a.topic.localeCompare(b.topic) || b.magnitude - a.magnitude);

  return (
    <div className="page">
      <section className="section">
        <div className="section-head">
          <h2>Literature report</h2>
          <span className="label">{data.findings.length} findings · {data.references.length} sources</span>
        </div>
        <p className="lede">
          Each entry connects one of your measurements to published research, the way a genotype report connects a DNA variant to the studies about it. The finding
          that applies depends on your value. <b>Magnitude</b> (0–4) says how much an entry is worth reading; the flag says whether the literature views your
          value as favourable, as worth attention, or as background context.
        </p>
        <ProfileNote profile={data.profile} />
        <p className="small">
          This is a reading aid, not a diagnosis. A wrist tracker estimates sleep and oxygen; the studies were done with clinical equipment. Bring anything
          flagged to a doctor rather than acting on it alone.
        </p>
        <div className="lit-controls">
          <div className="seg" role="group" aria-label="Show">
            {(
              [
                ["all", `All ${data.findings.length}`],
                ["attention", `Attention ${counts.attention}`],
                ["good", `Favourable ${counts.good}`],
                ["info", `Context ${counts.info}`],
              ] as [ReputeFilter, string][]
            ).map(([k, l]) => (
              <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>
                {l}
              </button>
            ))}
          </div>
          <div className="seg" role="group" aria-label="Order">
            {(["magnitude", "topic"] as const).map((k) => (
              <button key={k} aria-pressed={order === k} onClick={() => setOrder(k)}>
                By {k}
              </button>
            ))}
          </div>
        </div>
        <div>
          {shown.map((f) => (
            <FindingEntry key={f.id} f={f} numbers={numbers} />
          ))}
          {data.findings.length === 0 ? <NoFindings data={data} /> : shown.length === 0 && <p className="small">Nothing in this group.</p>}
        </div>
      </section>
      {data.references.length > 0 && (
        <section className="section">
          <div className="section-head">
            <h2>References</h2>
          </div>
          <ol className="refs">
            {data.references.map((r) => (
              <li key={r.id} id={`ref-${r.id}`}>
                {r.authors} <span className="r-title">{r.title}.</span> <i>{r.journal}</i> {r.year}
                {r.citation ? `;${r.citation}` : ""}.{" "}
                {r.pmid && <a href={`https://pubmed.ncbi.nlm.nih.gov/${r.pmid}/`} target="_blank" rel="noreferrer">PubMed {r.pmid}</a>}
                {r.pmid && r.doi && " · "}
                {r.doi && <a href={`https://doi.org/${r.doi}`} target="_blank" rel="noreferrer">doi:{r.doi}</a>}
                {!r.pmid && !r.doi && r.url && <a href={r.url} target="_blank" rel="noreferrer">Source</a>}
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

function FindingEntry({ f, numbers }: { f: Finding; numbers: Map<string, number> }) {
  return (
    <article className="finding" id={`finding-${f.id}`}>
      <div className="mag">
        <Pips n={f.magnitude} />
        <Flag repute={f.repute} />
      </div>
      <div>
        <div className="topic">{f.topic}</div>
        <h3>{f.title}</h3>
        {f.valueText && (
          <div className="yours">
            {f.valueLabel ?? "Your value"}: <b>{f.valueText}</b>
            {f.metric && f.basedOn != null && (
              <span className="based-on"> · based on {f.basedOn} night{f.basedOn === 1 ? "" : "s"}</span>
            )}
          </div>
        )}
        <p className="headline">
          {f.headline}
          <Cites ids={f.refs} numbers={numbers} />
        </p>
        {(f.detail || f.background || f.bands.length > 0 || f.caveat) && (
          <details>
            <summary>Evidence and details</summary>
            <div className="body">
              {f.bands.length > 0 && (
                <div className="bands" aria-label="Ranges">
                  {f.bands.map((b) => (
                    <span key={b.range} className={b.current ? "current" : ""}>
                      {b.range}
                    </span>
                  ))}
                </div>
              )}
              {f.detail && <p>{f.detail}</p>}
              {f.background && <p>{f.background}</p>}
              {f.caveat && <p className="caveat">{f.caveat}</p>}
            </div>
          </details>
        )}
      </div>
    </article>
  );
}

/* ------------------------------------------------------------------ method */

export function Method({ data }: { data: Summary }) {
  return (
    <div className="page">
      <section className="section">
        <div className="section-head">
          <h2>Method</h2>
          <span className="label">How the numbers are made</span>
        </div>
        <div className="lede">
          <p>
            Data comes from a Fitbit through the Google Health API: minute-level blood oxygen (SpO₂), Fitbit's sleep sessions with stages and brief
            awakenings, heart rate every ~2 seconds during sleep, and Fitbit's nightly breathing-rate summary. A night runs from 18:00 to 18:00 and is named
            after its evening; naps are Fitbit's non-main sleeps.
          </p>
          <h3 style={{ fontSize: "var(--step-1)", margin: "1.4em 0 0.4em" }}>Oxygen</h3>
          <p>
            Fitbit's SpO₂ values are a 5-minute moving average, and Google removes minutes it considers unreliable, so the line has gaps. The first two minutes
            after a gap read low while the average warms up and are left out. A dip is a fall of at least 3 (or 4) points below the level of the previous 10
            minutes; dips are counted per hour as the oxygen desaturation index (ODI). Because of the smoothing, short dips are flattened and the ODI here runs
            lower than a medical oximeter's.
          </p>
          <h3 style={{ fontSize: "var(--step-1)", margin: "1.4em 0 0.4em" }}>Heart rate</h3>
          <p>
            A surge is a rise of at least 10 bpm above the median of the previous minute, lasting at least 6 seconds, while asleep. Brief arousals and breathing
            events usually cause one. There is no clinical normal range for this wrist-based count: compare nights with each other, not with a threshold.
          </p>
          <h3 style={{ fontSize: "var(--step-1)", margin: "1.4em 0 0.4em" }}>Apnea-like heart-rate cycles</h3>
          <p>
            During an apnea the heart slows, and it speeds up abruptly when breathing resumes, so repeated apneas make heart rate cycle every 25 to 130
            seconds. The report follows the published ACAT method (Hayano et al.): interbeat intervals resampled at 2 Hz and smoothed, dips of 10–120 s
            that are deep relative to the surrounding 130 s, cycle lengths of 25–130 s, similar waveforms and regular cycles. The count is per hour in
            bed. The method was validated on ECG and on a watch's pulse wave, not on Fitbit's heart rate (one reading every ~2 s, taken as 60000/bpm), so
            the report also shows how many cycles it finds while you're awake: those are noise.
          </p>
          <h3 style={{ fontSize: "var(--step-1)", margin: "1.4em 0 0.4em" }}>Off nights</h3>
          <p>
            Each night's heart rate, HRV (Fitbit's nightly RMSSD), breathing rate and skin temperature (against Fitbit's baseline) are compared with your
            previous 28 nights. A signal counts as clearly off when it's more than 2 robust standard deviations away in the direction illness or alcohol
            push it (heart rate, breathing and temperature up; HRV down). A night with two or more clearly-off signals is an off night.
          </p>
          <h3 style={{ fontSize: "var(--step-1)", margin: "1.4em 0 0.4em" }}>Timing and regularity</h3>
          <p>
            The Sleep Regularity Index is the chance of being in the same state (asleep or awake) at two moments 24 hours apart, scaled from −100 to 100, using
            pairs of consecutive days that both have a recorded night. Social jetlag is the difference in mid-sleep between nights before Saturday and Sunday and
            the other nights.
          </p>
          <h3 style={{ fontSize: "var(--step-1)", margin: "1.4em 0 0.4em" }}>Your settings</h3>
          <p>
            Reference ranges depend on age: the sleep-quality and sleep-duration recommendations give separate ranges for teenagers (14–17), young
            adults (18–25), adults (26–64) and older adults (65 and over), and some findings are only based on adults. Your days off decide which
            nights count as free nights for social jetlag, and late sleep timing is measured from the bedtime your schedule asks of you. Shift work
            skips the late-timing and social-jetlag findings. Set all of this with <code>python -m sleep_report setup</code>.
          </p>
          <ProfileNote profile={data.profile} />
          <p className="small">Report generated {data.generated.replace("T", " ")}.</p>
        </div>
      </section>
    </div>
  );
}
