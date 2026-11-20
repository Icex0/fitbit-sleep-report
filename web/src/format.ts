// Number, time and date formatting used across the app.

const pad = (n: number) => String(n).padStart(2, "0");

/** Hours after 18:00 -> "02:31". */
export function clock(hoursAfter18: number): string {
  const m = Math.round(hoursAfter18 * 60);
  return `${pad((18 + Math.floor(m / 60)) % 24)}:${pad(((m % 60) + 60) % 60)}`;
}

/** Local ISO time -> "02:31". */
export function timeOf(iso: string): string {
  return iso.slice(11, 16);
}

const DAY = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });
const LONG = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const SHORT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });

const asDate = (ymd: string) => new Date(`${ymd}T12:00:00`);
export const dayLabel = (ymd: string) => DAY.format(asDate(ymd));
export const longDate = (ymd: string) => LONG.format(asDate(ymd));
export const shortDate = (ymd: string) => SHORT.format(asDate(ymd));
const DAY_MONTH = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long" });
const FULL = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric" });

/** "9 August – 26 October 2026" (the year once when both dates share it). */
export function period(first: string, last: string): string {
  const sameYear = first.slice(0, 4) === last.slice(0, 4);
  return `${(sameYear ? DAY_MONTH : FULL).format(asDate(first))} – ${FULL.format(asDate(last))}`;
}

/** 437 minutes -> "7 h 17 min". */
export function duration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes - h * 60);
  return h ? `${h} h ${pad(m)} min` : `${m} min`;
}

export const fixed = (v: number | null | undefined, digits = 1) => (v == null ? "–" : v.toFixed(digits));

/** Seconds after a start time -> clock time. */
export function clockAt(startIso: string, seconds: number): string {
  const d = new Date(startIso);
  d.setSeconds(d.getSeconds() + seconds);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
