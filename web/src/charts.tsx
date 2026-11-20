// Hand-built SVG charts: sleep diary, per-night trends, and the single-night panels.
import { useMemo, useState, type ReactNode } from "react";
import { scaleBand, scaleLinear } from "d3-scale";
import { line } from "d3-shape";
import { bisector } from "d3-array";
import { STAGES, stageOf, type NightDetail, type Recording, type StageCode } from "./data";
import { clock, clockAt, dayLabel, shortDate } from "./format";
import { Tooltip, TipRow, go, useWidth, type TipState } from "./ui";

const FONT = 11;

/** Every calendar date from the first to the last night, so gaps show as gaps. */
export function calendar(first: string, last: string): string[] {
  const out: string[] = [];
  const d = new Date(`${first}T12:00:00`);
  const end = new Date(`${last}T12:00:00`);
  while (d <= end) {
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`);
    d.setDate(d.getDate() + 1);
  }
  return out;
}
const isMonday = (ymd: string) => new Date(`${ymd}T12:00:00`).getDay() === 1;

/* ------------------------------------------------------------------ sleep diary */

export function SleepDiary({ recs, days, row = 11 }: { recs: Recording[]; days: string[]; row?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState | null>(null);
  const [hoverRow, setHoverRow] = useState<number | null>(null);
  const m = { top: 22, right: 8, bottom: 26, left: 78 };
  const height = m.top + m.bottom + days.length * row;
  const x = scaleLinear().domain([0, 24]).range([m.left, Math.max(m.left + 100, width - m.right)]);
  const byNight = useMemo(() => {
    const map = new Map<string, Recording[]>();
    recs.forEach((r) => map.set(r.night, [...(map.get(r.night) ?? []), r]));
    return map;
  }, [recs]);

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const i = Math.floor((e.clientY - box.top) / row);
    const day = days[i];
    if (day === undefined) return;
    setHoverRow(i);
    const items = byNight.get(day) ?? [];
    const night = items.find((r) => r.kind === "night");
    setTip({
      x: e.clientX - box.left + m.left,
      y: m.top + i * row + 14,
      content: (
        <>
          <div className="t-head">{dayLabel(day)} → next morning</div>
          {items.length === 0 && <div className="small">No sleep recorded</div>}
          {items.map((r) => (
            <TipRow
              key={r.id}
              value={`${clock(r.startH)}–${clock(r.endH)}`}
              label={r.kind === "nap" ? "nap" : r.sleep ? `${(r.sleep.asleep / 60).toFixed(1)} h asleep` : "night"}
            />
          ))}
          {night && <div className="small" style={{ marginTop: 4 }}>Click to open this night</div>}
        </>
      ),
    });
  };

  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={height} role="img" aria-label="Sleep diary: one row per night from 18:00 to 18:00, coloured by sleep stage">
        <defs>
          <clipPath id="diary-clip">
            <rect x={m.left} y={0} width={x(24) - m.left} height={height} />
          </clipPath>
        </defs>
        {[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => (
          <g key={h}>
            <line className="gridline" x1={x(h)} x2={x(h)} y1={m.top - 4} y2={height - m.bottom} />
            <text className="tick" x={x(h)} y={m.top - 10} textAnchor="middle" fill="var(--muted)" fontSize={FONT}>
              {clock(h)}
            </text>
          </g>
        ))}
        {days.map((day, i) => {
          const y = m.top + i * row;
          const items = byNight.get(day) ?? [];
          return (
            <g key={day}>
              {isMonday(day) && <line x1={0} x2={width - m.right} y1={y - 0.5} y2={y - 0.5} stroke="var(--rule)" />}
              {(isMonday(day) || (i === 0 && !days.slice(1, 3).some(isMonday))) && (
                <text x={0} y={y + row - 1} fill="var(--ink-2)" fontSize={Math.min(FONT, row + 3)}>
                  {dayLabel(day)}
                </text>
              )}
              {hoverRow === i && <rect x={m.left} y={y} width={x(24) - m.left} height={row} fill="var(--wash)" />}
              <g clipPath="url(#diary-clip)">
              {items.map((r) =>
                r.sleep && r.sleep.segments.length ? (
                  r.sleep.segments.map(([a, b, s], k) => (
                    <rect key={`${r.id}-${k}`} x={x(a)} y={y + 1} width={Math.max(0.6, x(b) - x(a))} height={row - 2} fill={stageOf(s).color} />
                  ))
                ) : (
                  <rect key={r.id} x={x(r.startH)} y={y + 1} width={x(r.endH) - x(r.startH)} height={row - 2} fill="var(--axis)" />
                ),
              )}
              </g>
            </g>
          );
        })}
        <rect
          x={m.left}
          y={m.top}
          width={x(24) - m.left}
          height={days.length * row}
          fill="transparent"
          style={{ cursor: "pointer" }}
          onPointerMove={onMove}
          onPointerLeave={() => {
            setTip(null);
            setHoverRow(null);
          }}
          onClick={() => {
            const night = hoverRow != null && (byNight.get(days[hoverRow]) ?? []).find((r) => r.kind === "night");
            if (night) go(`night/${night.id}`);
          }}
        />
      </svg>
      <Tooltip tip={tip} width={width} />
    </div>
  );
}

export function StageLegend({ withNoData = false }: { withNoData?: boolean }) {
  return (
    <div className="legend" aria-label="Sleep stages">
      {STAGES.filter((s) => ["D", "L", "R", "W"].includes(s.code))
        .slice()
        .reverse()
        .map((s) => (
          <span className="key" key={s.code}>
            <i className="swatch" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      {withNoData && (
        <span className="key">
          <i className="swatch" style={{ background: "var(--axis)" }} />
          No stage data
        </span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ trend chart */

export interface TrendSeries {
  key: string;
  label: string;
  color: string;
  kind: "column" | "line" | "dot";
  value: (r: Recording) => number | null;
  format: (v: number) => string;
}

interface TrendProps {
  title: string;
  unit?: string;
  days: string[];
  recs: Recording[]; // one per night
  series: TrendSeries[];
  stacked?: boolean; // stack all column series
  yDomain?: [number, number];
  yFormat?: (v: number) => string;
  refLine?: { value: number; label: string };
  refBand?: { from: number; to: number; label: string };
  height?: number;
  note?: ReactNode;
}

export function TrendChart({ title, unit, days, recs, series, stacked, yDomain, yFormat = String, refLine, refBand, height = 190, note }: TrendProps) {
  const [ref, width] = useWidth<HTMLDivElement>(500);
  const [tip, setTip] = useState<TipState | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const m = { top: 8, right: refLine || refBand ? 64 : 10, bottom: 24, left: 40 };
  const byDay = useMemo(() => new Map(recs.map((r) => [r.night, r])), [recs]);
  const x = scaleBand<string>().domain(days).range([m.left, Math.max(m.left + 50, width - m.right)]).padding(0.25);
  const step = x.step();

  const columns = series.filter((s) => s.kind === "column");
  const totals = days.map((d) => {
    const r = byDay.get(d);
    if (!r) return 0;
    return stacked ? columns.reduce((a, s) => a + (s.value(r) ?? 0), 0) : Math.max(0, ...series.map((s) => s.value(r) ?? 0));
  });
  const values = series.flatMap((s) => recs.map((r) => s.value(r)).filter((v): v is number => v != null));
  const domain: [number, number] = yDomain ?? [
    Math.min(0, ...values),
    Math.max(...totals, refLine ? refLine.value * 1.15 : 0, refBand ? refBand.to : 0) * 1.08 || 1,
  ];
  const y = scaleLinear().domain(domain).range([height - m.bottom, m.top]).nice(4);
  const ticks = y.ticks(4);
  const colW = Math.min(24, x.bandwidth());
  const labelEvery = Math.max(1, Math.ceil(52 / (7 * step))); // in weeks, keeps date labels >= 52px apart
  const radius = Math.min(4, colW / 3);

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const i = Math.max(0, Math.min(days.length - 1, Math.floor((e.clientX - box.left) / step)));
    setHover(i);
    const r = byDay.get(days[i]);
    setTip({
      x: x(days[i])! + x.bandwidth() / 2,
      y: m.top + 4,
      content: (
        <>
          <div className="t-head">{dayLabel(days[i])}</div>
          {!r && <div className="small">No data</div>}
          {r &&
            series.map((s) => {
              const v = s.value(r);
              return <TipRow key={s.key} value={v == null ? "–" : s.format(v)} label={s.label} color={s.color} swatch={s.kind === "column"} />;
            })}
        </>
      ),
    });
  };

  // a path per line series, broken where a night is missing
  const linePath = (s: TrendSeries) =>
    line<string>()
      .defined((d) => byDay.has(d) && s.value(byDay.get(d)!) != null)
      .x((d) => x(d)! + x.bandwidth() / 2)
      .y((d) => y(s.value(byDay.get(d)!)!))(days) ?? "";

  return (
    <div>
      <div className="chart-title">
        <h3>{title}</h3>
        {unit && <span className="unit">{unit}</span>}
      </div>
      {series.length > 1 && (
        <div className="legend">
          {series.map((s) => (
            <span className="key" key={s.key}>
              <i className={s.kind === "column" ? "swatch" : "linekey"} style={{ background: s.color, ...(s.kind === "dot" ? { width: 8, height: 8, borderRadius: 4 } : {}) }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
      <div className="chart" ref={ref}>
        <svg width={width} height={height} role="img" aria-label={title}>
          {refBand && (
            <g>
              <rect x={m.left} width={x.range()[1] - m.left} y={y(refBand.to)} height={y(refBand.from) - y(refBand.to)} fill="var(--series-1-wash)" />
              <text x={x.range()[1] + 6} y={y(refBand.to) + 4} fontSize={FONT} fill="var(--muted)">
                {refBand.label}
              </text>
            </g>
          )}
          {ticks.map((t) => (
            <g key={t}>
              <line className={t === domain[0] || t === 0 ? "baseline" : "gridline"} x1={m.left} x2={x.range()[1]} y1={y(t)} y2={y(t)} />
              <text x={m.left - 6} y={y(t) + 4} textAnchor="end" fontSize={FONT} fill="var(--muted)" className="num">
                {yFormat(t)}
              </text>
            </g>
          ))}
          {days.map((d, i) =>
            isMonday(d) && Math.floor(i / 7) % labelEvery === 0 ? (
              <text key={d} x={x(d)! + x.bandwidth() / 2} y={height - 6} textAnchor="middle" fontSize={FONT} fill="var(--muted)">
                {i < days.length - 3 ? shortDate(d) : ""}
              </text>
            ) : null,
          )}
          {hover != null && <rect x={x(days[hover])! - (step - x.bandwidth()) / 2} width={step} y={m.top} height={height - m.top - m.bottom} fill="var(--wash)" />}
          {days.map((d) => {
            const r = byDay.get(d);
            if (!r) return null;
            let base = 0;
            const cx = x(d)! + (x.bandwidth() - colW) / 2;
            return columns.map((s, k) => {
              const v = s.value(r);
              if (v == null || v <= 0) return null;
              const y0 = stacked ? base : 0;
              base = y0 + v;
              const top = y(y0 + v);
              const h = Math.max(0.5, y(y0) - top - (stacked && k > 0 ? 2 : 0));
              const isTop = !stacked || k === columns.length - 1 || columns.slice(k + 1).every((n) => !(n.value(r) ?? 0));
              return isTop ? (
                <path
                  key={s.key + d}
                  fill={s.color}
                  d={`M${cx},${top + h} V${top + radius} q0,-${radius} ${radius},-${radius} H${cx + colW - radius} q${radius},0 ${radius},${radius} V${top + h} Z`}
                />
              ) : (
                <rect key={s.key + d} x={cx} y={top} width={colW} height={h} fill={s.color} />
              );
            });
          })}
          {series
            .filter((s) => s.kind === "line")
            .map((s) => (
              <path key={s.key} d={linePath(s)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
            ))}
          {series
            .filter((s) => s.kind === "dot")
            .map((s) =>
              days.map((d) => {
                const r = byDay.get(d);
                const v = r ? s.value(r) : null;
                return v == null ? null : <circle key={s.key + d} cx={x(d)! + x.bandwidth() / 2} cy={y(v)} r={3.2} fill={s.color} stroke="var(--sheet)" strokeWidth={1.5} />;
              }),
            )}
          {refLine && (
            <g>
              <line x1={m.left} x2={x.range()[1]} y1={y(refLine.value)} y2={y(refLine.value)} stroke="var(--ink-2)" strokeWidth={1} strokeDasharray="4 3" />
              <text x={x.range()[1] + 6} y={y(refLine.value) + 4} fontSize={FONT} fill="var(--ink-2)">
                {refLine.label}
              </text>
            </g>
          )}
          <rect x={m.left} y={m.top} width={x.range()[1] - m.left} height={height - m.top - m.bottom} fill="transparent" onPointerMove={onMove} onPointerLeave={() => { setTip(null); setHover(null); }} onClick={() => { const r = hover != null && byDay.get(days[hover]); if (r) go(`night/${r.id}`); }} style={{ cursor: "pointer" }} />
        </svg>
        <Tooltip tip={tip} width={width} />
      </div>
      {note && <p className="small" style={{ marginTop: 6 }}>{note}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ one night */

const byTime = bisector<[number, number], number>((d) => d[0]).center;

function nearest(series: [number, number][], t: number, within: number): number | null {
  if (!series.length) return null;
  const i = byTime(series, t);
  return Math.abs(series[i][0] - t) <= within ? series[i][1] : null;
}

/** Keep a dense series drawable: per pixel column keep the min and max, so spikes survive. */
function thin(series: [number, number][], x: (t: number) => number): [number, number][] {
  const out: [number, number][] = [];
  let col = -1;
  let lo: [number, number] | null = null;
  let hi: [number, number] | null = null;
  const flush = () => {
    if (lo && hi) out.push(...((lo[0] < hi[0] ? [lo, hi] : [hi, lo]) as [number, number][]));
  };
  for (const p of series) {
    const c = Math.round(x(p[0]));
    if (c !== col) {
      flush();
      col = c;
      lo = hi = p;
    } else {
      if (p[1] < lo![1]) lo = p;
      if (p[1] > hi![1]) hi = p;
    }
  }
  flush();
  return out;
}

function brokenPath(series: [number, number][], x: (t: number) => number, y: (v: number) => number, gap: number) {
  let d = "";
  series.forEach(([t, v], i) => {
    const jump = i === 0 || t - series[i - 1][0] > gap;
    d += `${jump ? "M" : "L"}${x(t).toFixed(1)},${y(v).toFixed(1)}`;
  });
  return d;
}

export function NightPanels({ night }: { night: NightDetail }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const duration = (new Date(night.end).getTime() - new Date(night.start).getTime()) / 1000;
  const m = { left: 64, right: 12 };
  const x = scaleLinear().domain([0, duration]).range([m.left, Math.max(m.left + 100, width - m.right)]);

  const panels = [
    night.stages.length ? { key: "stages", label: "Sleep stage", h: 112 } : null,
    night.spo2.length ? { key: "spo2", label: "SpO₂ %", h: 170 } : null,
    night.hr.length ? { key: "hr", label: "Heart rate", h: 150 } : null,
  ].filter(Boolean) as { key: string; label: string; h: number }[];
  const gapBetween = 44;
  let top = 22;
  const layout = panels.map((p) => {
    const at = top;
    top += p.h + gapBetween;
    return { ...p, top: at };
  });
  const height = top - gapBetween + 30;

  const spo2Vals = night.spo2.map((d) => d[1]);
  const ySpo2 = scaleLinear().domain([Math.min(88, ...spo2Vals) - 1, 100]);
  const hrVals = night.hr.map((d) => d[1]);
  const yHr = scaleLinear().domain([Math.min(...hrVals) - 3, Math.max(...hrVals) + 3]).nice();

  const hours: number[] = [];
  const startDate = new Date(night.start);
  const firstHour = (60 - startDate.getMinutes()) * 60 - startDate.getSeconds();
  const everyHours = Math.max(1, Math.ceil(46 / (x(3600) - x(0)))); // keep hour labels >= 46px apart
  for (let t = firstHour; t <= duration; t += 3600 * everyHours) hours.push(t);

  const stageAt = (t: number): StageCode | null => night.stages.find(([a, b]) => a <= t && t < b)?.[2] ?? null;

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const t = Math.max(0, Math.min(duration, x.invert(e.clientX - box.left + m.left)));
    setCursor(t);
    const stage = stageAt(t);
    const brief = night.short.some(([a, b]) => a - 30 <= t && t <= b + 30);
    const s = nearest(night.spo2, t, 120);
    const h = nearest(night.hr, t, 15);
    setTip({
      x: x(t),
      y: 8,
      content: (
        <>
          <div className="t-head">{clockAt(night.start, t)}</div>
          {stage && <TipRow value={stageOf(stage).label + (brief ? " · brief awakening" : "")} label="" color={stageOf(stage).color} swatch />}
          {night.spo2.length > 0 && <TipRow value={s == null ? "–" : `${s.toFixed(1)}%`} label="SpO₂" color="var(--series-1)" />}
          {night.hr.length > 0 && <TipRow value={h == null ? "–" : `${h} bpm`} label="heart rate" color="var(--series-1)" />}
        </>
      ),
    });
  };

  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={height} role="img" aria-label="Night recording: sleep stages, oxygen saturation and heart rate over time">
        {hours.map((t) => (
          <g key={t}>
            <line className="gridline" x1={x(t)} x2={x(t)} y1={0} y2={height - 26} />
            <text x={x(t)} y={height - 8} textAnchor="middle" fontSize={FONT} fill="var(--muted)" className="num">
              {clockAt(night.start, t)}
            </text>
          </g>
        ))}
        {layout.map((p) => {
          const y0 = p.top;
          const y1 = p.top + p.h;
          return (
            <g key={p.key}>
              <text x={0} y={y0 - 6} fontSize={10.5} fontWeight={600} letterSpacing="0.08em" fill="var(--muted)">
                {p.label.toUpperCase()}
              </text>
              {p.key === "stages" && (
                <g>
                  {["Awake", "REM", "Light", "Deep"].map((name, i) => (
                    <text key={name} x={m.left - 8} y={y0 + 22 + i * 23 + 4} textAnchor="end" fontSize={FONT} fill="var(--ink-2)">
                      {name}
                    </text>
                  ))}
                  {night.stages.map(([a, b, code], i) => {
                    const st = stageOf(code);
                    return <rect key={i} x={x(a)} width={Math.max(0.8, x(b) - x(a))} y={y0 + 14 + st.row * 23} height={19} fill={st.color} />;
                  })}
                  {night.short.map(([a, b], i) => (
                    <rect key={`s${i}`} x={x(a)} width={Math.max(1.6, x(b) - x(a))} y={y0 + 14} height={19} fill="var(--stage-wake)" opacity={0.85} />
                  ))}
                </g>
              )}
              {p.key === "spo2" && (() => {
                const y = ySpo2.copy().range([y1, y0 + 14]);
                return (
                  <g>
                    {y.ticks(4).map((t) => (
                      <g key={t}>
                        <line className="gridline" x1={m.left} x2={x.range()[1]} y1={y(t)} y2={y(t)} />
                        <text x={m.left - 8} y={y(t) + 4} textAnchor="end" fontSize={FONT} fill="var(--muted)" className="num">{t}</text>
                      </g>
                    ))}
                    {night.dips.map(([a, b], i) => (
                      <rect key={i} x={x(a - 30)} width={Math.max(3, x(b + 30) - x(a - 30))} y={y0 + 14} height={y1 - y0 - 14} fill="var(--event)" opacity={0.2} />
                    ))}
                    <line x1={m.left} x2={x.range()[1]} y1={y(90)} y2={y(90)} stroke="var(--ink-2)" strokeDasharray="4 3" />
                    <text x={x.range()[1] - 4} y={y(90) - 5} textAnchor="end" fontSize={FONT} fill="var(--ink-2)">90%</text>
                    <path d={brokenPath(night.spo2, x, y, 180)} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                    {night.settling.map((t) => {
                      const v = nearest(night.spo2, t, 1);
                      return v == null ? null : <circle key={t} cx={x(t)} cy={y(v)} r={3} fill="var(--muted)" stroke="var(--sheet)" strokeWidth={1.5} />;
                    })}
                  </g>
                );
              })()}
              {p.key === "hr" && (() => {
                const y = yHr.copy().range([y1, y0 + 14]);
                return (
                  <g>
                    {y.ticks(4).map((t) => (
                      <g key={t}>
                        <line className="gridline" x1={m.left} x2={x.range()[1]} y1={y(t)} y2={y(t)} />
                        <text x={m.left - 8} y={y(t) + 4} textAnchor="end" fontSize={FONT} fill="var(--muted)" className="num">{t}</text>
                      </g>
                    ))}
                    <path d={brokenPath(thin(night.hr, x), x, y, 60)} fill="none" stroke="var(--series-1)" strokeWidth={1} strokeLinejoin="round" />
                    {(night.cvhr ?? []).map((t) => (
                      <line key={`c${t}`} x1={x(t)} x2={x(t)} y1={y1 - 10} y2={y1} stroke="var(--stage-rem)" strokeWidth={1.5} />
                    ))}
                    {night.surges.map(([t, peak], i) => (
                      <path key={i} d={`M${x(t)},${y(peak) - 9} l4.5,8 h-9 z`} fill="var(--event)" stroke="var(--sheet)" strokeWidth={1.5} strokeLinejoin="round" />
                    ))}
                  </g>
                );
              })()}
            </g>
          );
        })}
        {cursor != null && <line className="crosshair" x1={x(cursor)} x2={x(cursor)} y1={0} y2={height - 26} />}
        <rect x={m.left} y={0} width={x.range()[1] - m.left} height={height - 26} fill="transparent" onPointerMove={onMove} onPointerLeave={() => { setTip(null); setCursor(null); }} />
      </svg>
      <Tooltip tip={tip} width={width} />
    </div>
  );
}
