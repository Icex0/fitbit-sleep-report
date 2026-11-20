import { useCallback, useEffect, useState } from "react";
import { clearCache, loadSummary, SOURCE_LABEL, type Summary } from "./data";
import { period } from "./format";
import { Literature, Method, NightPage, NightsTable, Overview } from "./pages";
import { SetupPage } from "./setup";
import { SummaryPage } from "./summary";
import { useRoute, useTheme } from "./ui";

const NAV = [
  ["", "Overview"],
  ["nights", "Nights"],
  ["literature", "Literature"],
  ["method", "Method"],
  ["summary", "Summary"],
  ["setup", "Setup"],
] as const;

export default function App() {
  const route = useRoute();
  const [theme, nextTheme] = useTheme();
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    loadSummary().then(
      (d) => {
        setData(d);
        setError(null);
      },
      (e) => setError(String(e)),
    );
  }, [version]);
  const reload = useCallback(() => {
    clearCache();
    setVersion((v) => v + 1);
  }, []);

  const section = route[0] ?? "";
  const nights = data?.recordings.filter((r) => r.kind === "night") ?? [];
  const showSetup = section === "setup" || (!data && !!error) || (!!data && !nights.length);
  const current = showSetup ? "setup" : section === "night" ? "nights" : section;
  const naps = (data?.recordings.length ?? 0) - nights.length;

  return (
    <main className="sheet">
      <header className="masthead">
        <div>
          <div className="kicker">Sleep report</div>
          <h1>{nights.length ? period(nights[0].night, nights[nights.length - 1].night) : "Sleep report"}</h1>
          {data && (
            <p className="subject">
              <span>{nights.length} nights</span>
              <span>{naps} naps</span>
              <span>{SOURCE_LABEL[data.profile?.source ?? "google"]}</span>
            </p>
          )}
        </div>
        <nav className="nav" aria-label="Sections">
          {NAV.map(([path, label]) => (
            <a key={path} href={`#/${path}`} aria-current={current === path ? "page" : undefined}>
              {label}
            </a>
          ))}
          <button className="theme-toggle" onClick={nextTheme} title="Switch between system, light and dark">
            {theme === "system" ? "Auto" : theme === "light" ? "Light" : "Dark"}
          </button>
        </nav>
      </header>

      {showSetup && (
        <SetupPage onDataChanged={reload} firstRun={!data || !nights.length} />
      )}
      {!showSetup && data && nights.length > 0 && (
        <>
          {section === "" && <Overview data={data} />}
          {section === "nights" && <NightsTable data={data} />}
          {section === "night" && route[1] && <NightPage data={data} id={route[1]} />}
          {section === "literature" && <Literature data={data} />}
          {section === "method" && <Method data={data} />}
          {section === "summary" && <SummaryPage data={data} />}
        </>
      )}

      <footer className="disclaimer">
        Personal report made from a consumer wearable. Not a medical device and not a diagnosis; sleep stages and oxygen from a wrist tracker are
        estimates. If you are often tired, snore, or someone has seen you stop breathing in your sleep, talk to a doctor.
      </footer>
    </main>
  );
}
