// A printable one-glance summary: what stands out, key measurements against references, the
// sleep diary, limitations and sources. Built from the same findings as the report.
import { calendar, SleepDiary, StageLegend } from "./charts";
import { SOURCE_LABEL, type Finding, type Summary } from "./data";
import { period } from "./format";
import { Flag } from "./ui";

// Measurements in the order a clinician would read them; absent ones are skipped.
const MEASURES = [
  "sleep-duration", "nights-under-7", "nights-under-8", "short-sleep-performance",
  "delayed-timing", "onset-before-2am", "sleep-regularity", "sleep-duration-spread", "irregular-sleep-heart",
  "social-jetlag",
  "sleep-efficiency", "sleep-latency", "waso", "long-awakenings", "deep-sleep", "rem-sleep",
  "evening-naps", "naps-length",
  "odi", "spo2-level", "cvhr", "breathing-rate",
  "resting-hr", "hrv-norm", "off-nights",
];

export function SummaryPage({ data }: { data: Summary }) {
  const byId = new Map(data.findings.map((f) => [f.id, f]));
  const measures = MEASURES.map((id) => byId.get(id)).filter((f): f is Finding => !!f && f.valueText != null);
  const discuss = data.findings.filter((f) => f.repute === "attention" || (f.id === "cvhr" && (f.value ?? 0) >= 8));
  const used = [...new Set([...measures, ...discuss].flatMap((f) => f.refs))];
  const refs = used.map((id) => data.references.find((r) => r.id === id)).filter(Boolean) as Summary["references"];
  const number = new Map(refs.map((r, i) => [r.id, i + 1]));
  const nights = data.recordings.filter((r) => r.kind === "night");
  const days = calendar(nights[0].night, nights[nights.length - 1].night);
  const p = data.profile;
  const apple = p?.source === "apple";

  return (
    <div className="page summary">
      <section className="section">
        <div className="section-head">
          <h2>Summary</h2>
          <button className="btn secondary no-print" onClick={() => window.print()}>Print or save as PDF</button>
        </div>
        <p className="lede">
          {period(nights[0].night, nights[nights.length - 1].night)}: {nights.length} nights and {data.recordings.length - nights.length} naps recorded with
          a consumer wrist tracker ({SOURCE_LABEL[p?.source ?? "google"]}). Values are medians across nights unless stated.
        </p>
        {p && (
          <dl className="facts">
            <div><dt>Age</dt><dd>{p.age ?? "not given"}</dd></div>
            <div><dt>Often tired during the day</dt><dd>{p.oftenTired == null ? "not given" : p.oftenTired ? "yes" : "no"}</dd></div>
            <div><dt>Bedtime the schedule asks for</dt><dd>{p.usualBedtime}</dd></div>
            <div><dt>Days off</dt><dd>{p.daysOff.join(", ") || "none"}</dd></div>
            <div><dt>Shift work</dt><dd>{p.shiftWork ? "yes" : "no"}</dd></div>
          </dl>
        )}
      </section>

      {discuss.length > 0 && (
        <section className="section">
          <div className="section-head">
            <h2>What stands out</h2>
          </div>
          <ul className="discuss">
            {discuss.map((f) => (
              <li key={f.id}>
                <b>{f.title}{f.valueText ? `: ${f.valueText}` : ""}.</b> {f.headline}
                <span className="cite">{f.refs.map((r) => `[${number.get(r)}]`).join("")}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="section">
        <div className="section-head">
          <h2>Measurements</h2>
          <span className="label">Against published reference values</span>
        </div>
        <table className="results compact">
          <thead>
            <tr><th scope="col">Measure</th><th scope="col">Value</th><th scope="col">Reference</th><th scope="col">Flag</th><th scope="col">Source</th></tr>
          </thead>
          <tbody>
            {measures.map((f) => (
              <tr key={f.id}>
                <th scope="row">{f.valueLabel ?? f.title}</th>
                <td className="value">{f.valueText}</td>
                <td className="ref">{f.reference ?? "–"}</td>
                <td><Flag repute={f.repute} /></td>
                <td className="ref">{f.refs.map((r) => `[${number.get(r)}]`).join("")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="section diary-print">
        <div className="section-head">
          <h2>Sleep diary</h2>
          <span className="label">Each row is one night, 18:00 to 18:00</span>
        </div>
        <StageLegend withNoData={nights.some((r) => !r.sleep)} />
        <SleepDiary recs={data.recordings} days={days} row={7} />
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Limitations</h2>
        </div>
        <p className="small">
          A wrist tracker is not a medical device. Sleep stages are estimated and wake time is under-detected, so efficiency is likely overestimated.{" "}
          {apple
            ? "The Apple Watch measures blood oxygen only now and then and heart rate every few minutes during sleep, so oxygen dips and heart-rate cycles aren't counted; its HRV is SDNN, not comparable with RMSSD reference values."
            : "SpO₂ is a 5-minute moving average with unreliable minutes removed, which flattens short desaturations; the oxygen desaturation index here is lower than a clinical oximeter's. The heart-rate cycle count (CVHR) follows a method validated on ECG and on a watch's pulse intervals, not on Fitbit's 2-second heart rate."}{" "}
          Reference values come from the cited studies, which used clinical or research equipment.
        </p>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Sources</h2>
        </div>
        <ol className="refs">
          {refs.map((r) => (
            <li key={r.id}>
              {r.authors} {r.title}. <i>{r.journal}</i> {r.year}{r.citation ? `;${r.citation}` : ""}.{r.pmid ? ` PMID ${r.pmid}.` : ""}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
