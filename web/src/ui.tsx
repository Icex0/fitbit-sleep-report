// Small shared pieces: sizing, routing, theme, tooltip, status flag.
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

/** Width of an element, kept up to date with a ResizeObserver. */
export function useWidth<T extends HTMLElement>(fallback = 800) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

/** Current hash route, e.g. "#/night/night-2026-10-21" -> ["night", "night-2026-10-21"]. */
export function useRoute(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => {
      setRoute(read());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export const go = (path: string) => {
  window.location.hash = `#/${path}`;
};

type Theme = "system" | "light" | "dark";
const THEME_KEY = "sleep-report-theme";

function readTheme(): Theme {
  try {
    const t = localStorage.getItem(THEME_KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* storage unavailable: theme just isn't remembered */
    }
  }, [theme]);
  const next = () => setTheme((t) => (t === "system" ? "light" : t === "light" ? "dark" : "system"));
  return [theme, next] as const;
}

export interface TipState {
  x: number;
  y: number;
  content: ReactNode;
}

/** Tooltip positioned inside a `.chart` container, flipped to stay inside it. */
export function Tooltip({ tip, width }: { tip: TipState | null; width: number }) {
  if (!tip) return null;
  const left = tip.x > width - 220 ? tip.x - 14 : tip.x + 14;
  return (
    <div
      className="tooltip"
      role="status"
      style={{ left, top: tip.y, transform: tip.x > width - 220 ? "translateX(-100%)" : undefined }}
    >
      {tip.content}
    </div>
  );
}

export function TipRow({ value, label, color, swatch }: { value: ReactNode; label: string; color?: string; swatch?: boolean }) {
  return (
    <div className="t-row">
      {color && <i className={swatch ? "t-swatch" : "t-key"} style={{ background: color }} />}
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}

const FLAG_TEXT = { good: "Favourable", attention: "Attention", info: "Context" } as const;

/** Repute flag: icon + word, never colour alone. */
export function Flag({ repute, label }: { repute: "good" | "attention" | "info"; label?: string }) {
  return (
    <span className={`flag ${repute}`} title={label ?? FLAG_TEXT[repute]}>
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
        {repute === "good" && (
          <>
            <circle cx="7" cy="7" r="6" fill="none" stroke="var(--good)" strokeWidth="1.5" />
            <path d="M4 7.2l2 2 4-4.4" fill="none" stroke="var(--good)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </>
        )}
        {repute === "attention" && (
          <>
            <path d="M7 1.5l5.8 10.5H1.2z" fill="none" stroke="var(--attention)" strokeWidth="1.5" strokeLinejoin="round" />
            <path d="M7 5.5v3" stroke="var(--attention)" strokeWidth="1.6" strokeLinecap="round" />
            <circle cx="7" cy="10.2" r="0.9" fill="var(--attention)" />
          </>
        )}
        {repute === "info" && (
          <>
            <circle cx="7" cy="7" r="6" fill="none" stroke="var(--info)" strokeWidth="1.5" />
            <path d="M7 6.2v4" stroke="var(--info)" strokeWidth="1.6" strokeLinecap="round" />
            <circle cx="7" cy="4.2" r="0.9" fill="var(--info)" />
          </>
        )}
      </svg>
      <span className="flag-text">{label ?? FLAG_TEXT[repute]}</span>
    </span>
  );
}

export function Pips({ n, max = 4 }: { n: number; max?: number }) {
  return (
    <span className="pips" role="img" aria-label={`Magnitude ${n} of ${max}`}>
      {Array.from({ length: max }, (_, i) => (
        <i key={i} className={i < n ? "on" : ""} />
      ))}
    </span>
  );
}
