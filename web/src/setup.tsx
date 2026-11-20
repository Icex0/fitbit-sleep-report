// Setup page: what's done, sign in, download data, and the settings that pick reference ranges.
// Talks to the local bridge in api-plugin.ts, which runs the sleep_report commands.
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Flag } from "./ui";

type Device = "google" | "apple";

interface Settings {
  device: Device;
  age: number | null;
  days_off: string[];
  usual_bedtime: string;
  shift_work: boolean;
  often_tired: boolean | null;
}

interface Status {
  source: Device | null; // which device the current data came from
  credentials: boolean;
  signedIn: boolean;
  signedInAt: string | null;
  scopes: { spo2: boolean; sleep: boolean };
  lastFetch: { at: string; days: number } | null;
  data: { spo2Readings: number; sleepSessions: number } | null;
  exported: string | null;
  settings: Settings | null;
  settingsSaved: boolean;
  settingsError: string | null;
}

interface Job {
  id: number;
  kind: "auth" | "fetch" | "export" | "settings" | "import";
  status: "running" | "done" | "failed" | "cancelled";
  log: string;
  started: string;
  finished?: string;
}

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const JOB_LABEL = { auth: "Signing in", fetch: "Downloading data", export: "Rebuilding the report", settings: "Saving settings", import: "Importing your export" };
const DEVICE_LABEL: Record<Device, string> = { google: "Fitbit or Pixel Watch", apple: "Apple Watch" };
const SIGN_IN_DAYS = 7; // Google expires sign-ins of apps in "Testing" mode after a week

async function api<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json", "X-Sleep-Report": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const ct = res.headers.get("Content-Type") ?? "";
  if (!ct.includes("application/json")) throw new Error("no-api");
  const data = await res.json();
  if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
  return data as T;
}

/** Upload an Apple Health export as the raw request body, reporting progress (0-1). */
function uploadExport(file: File, replace: boolean, onProgress: (share: number) => void): Promise<{ job: Job }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/import-apple${replace ? "?replace=1" : ""}`);
    xhr.setRequestHeader("X-Sleep-Report", "1");
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status >= 400) reject(new Error(data.error ?? `HTTP ${xhr.status}`));
        else resolve(data);
      } catch {
        reject(new Error(`HTTP ${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error("The upload failed."));
    xhr.send(file);
  });
}

/** The terminal's carriage-return progress lines, collapsed the way a terminal shows them. */
function terminalText(log: string) {
  return log
    .split("\n")
    .map((line) => line.split("\r").filter(Boolean).pop() ?? "")
    .join("\n")
    .trimEnd();
}

const when = (iso: string) =>
  new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));

export function SetupPage({ onDataChanged, firstRun }: { onDataChanged: () => void; firstRun: boolean }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [noApi, setNoApi] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seenJob = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api<{ status: Status; job: Job | null }>("status");
      setStatus(r.status);
      setJob(r.job);
      setNoApi(false);
    } catch (e) {
      if (e instanceof Error && e.message === "no-api") setNoApi(true);
      else setError(String(e instanceof Error ? e.message : e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // poll while a task runs; when it finishes, refresh the status and the report
  useEffect(() => {
    if (job?.status !== "running") return;
    const t = setInterval(async () => {
      try {
        const r = await api<{ job: Job | null }>("job");
        setJob(r.job);
      } catch {
        /* keep the last state; the next tick tries again */
      }
    }, 1000);
    return () => clearInterval(t);
  }, [job?.status, job?.id]);

  useEffect(() => {
    if (!job || job.status === "running" || seenJob.current === job.id) return;
    seenJob.current = job.id;
    refresh();
    if (job.status === "done" && job.kind !== "auth") onDataChanged();
  }, [job, refresh, onDataChanged]);

  const start = async (path: string, body: unknown = {}) => {
    setError(null);
    try {
      const r = await api<{ job: Job }>(path, body);
      seenJob.current = null;
      setJob(r.job);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (noApi) return <NoBridge />;
  if (!status) return <p className="lede section">{error ?? "Checking setup…"}</p>;

  const running = job?.status === "running";
  const device: Device = status.settings?.device ?? "google";
  const settings = status.settings ?? { device, age: null, days_off: ["Sat", "Sun"], usual_bedtime: "23:00", shift_work: false, often_tired: null };
  const chooseDevice = async (d: Device) => {
    setError(null);
    try {
      await api(`settings?rebuild=0`, { ...settings, device: d });
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  const otherSource = status.source && status.source !== device ? status.source : null;
  const signedIn = status.signedIn && status.scopes.spo2;
  const expires = status.signedInAt ? new Date(new Date(status.signedInAt).getTime() + SIGN_IN_DAYS * 86400_000) : null;
  const expired = expires ? expires.getTime() < Date.now() : false;
  const hasData = !!status.data && status.source === device && (status.data.spo2Readings > 0 || status.data.sleepSessions > 0);
  const steps = device === "google" ? 5 : 4;

  return (
    <div className="page">
      <section className="section">
        <div className="section-head">
          <h2>Setup</h2>
          <span className="label">{firstRun ? `${steps} steps to your first report` : "Device, data and your settings"}</span>
        </div>
        {firstRun && (
          <p className="lede">
            This app turns your watch's sleep, blood oxygen, heart rate and breathing data into a report, with what published research says about your
            numbers. Everything stays on this computer.
          </p>
        )}

        <ol className="steps">
          <Step n={1} title="Your device" done={status.settingsSaved || hasData} state={DEVICE_LABEL[device]}>
            <div className="seg" role="group" aria-label="Device">
              {(Object.keys(DEVICE_LABEL) as Device[]).map((d) => (
                <button key={d} type="button" aria-pressed={device === d} disabled={running} onClick={() => chooseDevice(d)}>
                  {DEVICE_LABEL[d]}
                </button>
              ))}
            </div>
            <p className="small" style={{ marginTop: 8 }}>
              {device === "google"
                ? "Fitbit and Pixel Watch data is downloaded from Google: the most complete data, including blood oxygen every minute and heart rate every few seconds."
                : "Apple Watch data comes from an export of the Health app. Blood oxygen and heart rate are measured too rarely for some analyses; the report says which."}
            </p>
          </Step>
          {device === "apple" ? (
            <>
              <Step n={2} title="Export from your iPhone" done={hasData} state={hasData ? "Done" : "On your iPhone"}>
                <p>
                  Open the <b>Health</b> app, tap your profile picture (top right), then <b>Export All Health Data</b> and <b>Export</b>. Preparing it can take a
                  few minutes. Send the <code>export.zip</code> to this computer, for example with AirDrop, iCloud Drive or email.
                </p>
              </Step>
              <Step n={3} title="Upload the export" done={hasData} state={hasData ? dataText(status) : "No data yet"}>
                <UploadControls running={running} otherSource={otherSource} hasData={hasData}
                  onUploaded={(j) => { seenJob.current = null; setJob(j); }} onError={setError} />
              </Step>
              <Step n={4} title="About you" done={status.settingsSaved}
                state={status.settingsSaved ? "Saved" : "Not set: adult ranges, days off Sat and Sun, bedtime 23:00"}>
                <SettingsForm initial={settings} saveError={status.settingsError} running={running} hasData={hasData}
                  onSave={(s) => start("settings", s)} />
              </Step>
            </>
          ) : (
          <>
          <Step n={2} title="Google credentials" done={status.credentials}
            state={status.credentials ? "client_secret.json found" : "Not set up yet"}>
            {!status.credentials && (
              <>
                <p>
                  Google only lets programs read your health data through an app you register yourself (free, about 10 minutes). Follow steps 2.1 to 2.6 in
                  the project's README: create a Google Cloud project, enable the <b>Google Health API</b>, add yourself as a test user, add the two
                  read-only scopes, and create a <b>Web application</b> client with redirect URI <code>http://localhost:8080/</code>.
                </p>
                <p>Download the client's JSON file, save it as <code>client_secret.json</code> in the project folder, then check again.</p>
                <button className="btn" onClick={refresh}>Check again</button>
              </>
            )}
          </Step>

          <Step n={3} title="Sign in with Google" done={signedIn && !expired} blocked={!status.credentials}
            state={!status.signedIn ? "Not signed in" : expired ? "Sign-in has probably expired" : signedIn ? signInText(status, expires) : "Signed in, but SpO2 access is missing"}>
            {status.credentials && (
              <>
                {(!signedIn || expired || !status.scopes.sleep) && (
                  <p>
                    A browser tab opens. Choose the Google account your Fitbit uses and allow <b>both</b> permissions. Google will say the app isn't verified:
                    that's your own app, so choose <b>Advanced → Go to …</b>.
                    {!status.scopes.sleep && status.signedIn && " Sleep access is missing, so sleep stages and heart rate can't be downloaded."}
                  </p>
                )}
                {signedIn && !expired && (
                  <p className="small">Google ends sign-ins for apps in testing mode after 7 days. If a download fails with a sign-in error, sign in again here.</p>
                )}
                <button className={`btn ${signedIn && !expired ? "secondary" : ""}`} disabled={running} onClick={() => start("auth")}>
                  {status.signedIn ? "Sign in again" : "Sign in with Google"}
                </button>
              </>
            )}
          </Step>

          <Step n={4} title="Download your data" done={hasData} blocked={!signedIn}
            state={hasData ? dataText(status) : "No data yet"}>
            {otherSource && (
              <p className="small">
                Your current data comes from an {DEVICE_LABEL[otherSource]}. Downloading won't mix the two: keep it in a separate folder, or switch the
                device back above.
              </p>
            )}
            {signedIn && <FetchControls hasData={hasData} running={running} onFetch={(days) => start("fetch", { days })} />}
            {hasData && !status.exported && (
              <div className="row-controls" style={{ marginTop: 12 }}>
                <span className="small">The report hasn't been built from this data yet.</span>
                <button className="btn secondary" disabled={running} onClick={() => start("export")}>Build the report</button>
              </div>
            )}
          </Step>

          <Step n={5} title="About you" done={status.settingsSaved}
            state={status.settingsSaved ? "Saved" : "Not set: adult ranges, days off Sat and Sun, bedtime 23:00"}>
            <SettingsForm initial={settings} saveError={status.settingsError} running={running} hasData={hasData}
              onSave={(s) => start("settings", s)} />
          </Step>
          </>
          )}
        </ol>
        {error && <p className="form-error" role="alert">{error}</p>}
      </section>

      {job && <JobPanel job={job} onCancel={() => start("cancel")} />}
    </div>
  );
}

function signInText(s: Status, expires: Date | null) {
  const scopes = s.scopes.sleep ? "SpO2 and sleep" : "SpO2 only";
  if (!expires) return `Signed in (${scopes})`;
  const days = Math.max(0, Math.ceil((expires.getTime() - Date.now()) / 86400_000));
  return `Signed in (${scopes}) · about ${days} day${days === 1 ? "" : "s"} left`;
}

function dataText(s: Status) {
  const d = s.data!;
  const parts = [`${d.spo2Readings.toLocaleString("en-GB")} SpO2 readings`, `${d.sleepSessions} sleep sessions`];
  if (s.lastFetch) parts.push(`last download ${when(s.lastFetch.at)}`);
  return parts.join(" · ");
}

function Step({ n, title, state, done, blocked, children }: { n: number; title: string; state: string; done: boolean; blocked?: boolean; children?: ReactNode }) {
  return (
    <li className={`step ${blocked ? "blocked" : ""}`}>
      <span className="step-n" aria-hidden="true">{n}</span>
      <div className="step-body">
        <div className="step-head">
          <h3>{title}</h3>
          {done ? <Flag repute="good" label="Done" /> : blocked ? <Flag repute="info" label="After the step above" /> : <Flag repute="attention" label="To do" />}
        </div>
        <p className="step-state">{state}</p>
        {!blocked && children}
      </div>
    </li>
  );
}

function UploadControls({ running, otherSource, hasData, onUploaded, onError }: {
  running: boolean; otherSource: Device | null; hasData: boolean; onUploaded: (job: Job) => void; onError: (e: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [replace, setReplace] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const blocked = !!otherSource && !replace;
  const go = async () => {
    if (!file) return;
    setProgress(0);
    try {
      const r = await uploadExport(file, !!otherSource && replace, setProgress);
      onUploaded(r.job);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setProgress(null);
    }
  };
  return (
    <div>
      {otherSource && (
        <label className="field check" style={{ marginBottom: 10 }}>
          <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
          <span>Replace my current {DEVICE_LABEL[otherSource]} data (it will be deleted from this computer)</span>
        </label>
      )}
      <div className="row-controls">
        <input type="file" accept=".zip,.xml" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <button className="btn" disabled={!file || running || blocked || progress != null} onClick={go}>
          {hasData ? "Upload a newer export" : "Upload and import"}
        </button>
        {progress != null && <span className="small">Uploading… {Math.round(progress * 100)}%</span>}
      </div>
      <p className="small" style={{ marginTop: 8 }}>
        Large exports (hundreds of MB) take a minute or two to read. Each upload replaces the previous import, so upload a fresh export when you want newer
        nights.
      </p>
    </div>
  );
}

function FetchControls({ hasData, running, onFetch }: { hasData: boolean; running: boolean; onFetch: (days: number) => void }) {
  const [days, setDays] = useState(hasData ? 7 : 90);
  return (
    <div className="row-controls">
      <label className="field inline">
        <span>Download the last</span>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 14, 30, 90, 180, 365].map((d) => (
            <option key={d} value={d}>{d} days</option>
          ))}
        </select>
      </label>
      <button className="btn" disabled={running} onClick={() => onFetch(days)}>
        {hasData ? "Download new data" : "Download"}
      </button>
      {!hasData && <span className="small">The first download takes a few minutes: heart rate comes in every 2 seconds.</span>}
    </div>
  );
}

function SettingsForm({ initial, saveError, running, hasData, onSave }: {
  initial: Settings | null; saveError: string | null; running: boolean; hasData: boolean; onSave: (s: Settings) => void;
}) {
  const [age, setAge] = useState(initial?.age != null ? String(initial.age) : "");
  const [daysOff, setDaysOff] = useState<string[]>(initial?.days_off ?? ["Sat", "Sun"]);
  const [bedtime, setBedtime] = useState(initial?.usual_bedtime ?? "23:00");
  const [shift, setShift] = useState(initial?.shift_work ?? false);
  const [tired, setTired] = useState<boolean | null>(initial?.often_tired ?? null);
  const [problem, setProblem] = useState<string | null>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const n = age.trim() === "" ? null : Number(age);
    if (n !== null && (!Number.isInteger(n) || n < 14 || n > 119)) {
      setProblem("Enter an age of 14 or over, or leave it empty.");
      return;
    }
    setProblem(null);
    onSave({ device: initial?.device ?? "google", age: n, days_off: DAYS.filter((d) => daysOff.includes(d)), usual_bedtime: bedtime, shift_work: shift, often_tired: tired });
  };

  return (
    <form className="settings-form" onSubmit={submit}>
      <p className="small">These pick the reference ranges in the literature report: they differ by age group, and some findings assume a day schedule.</p>
      <label className="field">
        <span>Age</span>
        <input type="number" inputMode="numeric" min={14} max={119} value={age} placeholder="Not set" onChange={(e) => setAge(e.target.value)} />
        <small>Teenagers (14–17), young adults (18–25), adults (26–64) and older adults (65+) have different ranges.</small>
      </label>
      <fieldset className="field">
        <legend>Days off</legend>
        <div className="seg days" role="group">
          {DAYS.map((d) => (
            <button type="button" key={d} aria-pressed={daysOff.includes(d)}
              onClick={() => setDaysOff((cur) => (cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d]))}>
              {d}
            </button>
          ))}
        </div>
        <small>The nights before these days count as free nights when measuring social jetlag.</small>
      </fieldset>
      <label className="field">
        <span>Usual bedtime</span>
        <input type="time" value={bedtime} step={300} onChange={(e) => setBedtime(e.target.value)} required />
        <small>The bedtime your schedule asks of you. Late sleep timing is measured from it.</small>
      </label>
      <label className="field check">
        <input type="checkbox" checked={shift} onChange={(e) => setShift(e.target.checked)} />
        <span>I work night or rotating shifts</span>
      </label>
      <fieldset className="field">
        <legend>Are you often tired during the day?</legend>
        <div className="seg" role="group">
          {([[true, "Yes"], [false, "No"], [null, "Not sure"]] as const).map(([v, l]) => (
            <button type="button" key={l} aria-pressed={tired === v} onClick={() => setTired(v)}>{l}</button>
          ))}
        </div>
      </fieldset>
      {(problem || saveError) && <p className="form-error" role="alert">{problem ?? `Current settings.json: ${saveError}`}</p>}
      <div className="row-controls">
        <button className="btn" type="submit" disabled={running}>{hasData ? "Save and update the report" : "Save"}</button>
      </div>
    </form>
  );
}

function JobPanel({ job, onCancel }: { job: Job; onCancel: () => void }) {
  const text = terminalText(job.log);
  const ref = useRef<HTMLPreElement>(null);
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight });
  }, [text]);
  const outcome = { running: "In progress", done: "Finished", failed: "Failed", cancelled: "Stopped" }[job.status];
  return (
    <section className="section" aria-live="polite">
      <div className="section-head">
        <h2>{JOB_LABEL[job.kind]}</h2>
        <span className="label">{outcome}</span>
      </div>
      {job.kind === "auth" && job.status === "running" && (
        <p className="lede">Finish signing in in the browser tab that opened. This page updates when you're done.</p>
      )}
      {job.status === "failed" && <p className="form-error">Something went wrong; the output below says what.</p>}
      <pre className="log" ref={ref}>{text || "Starting…"}</pre>
      {job.status === "running" && (
        <button className="btn secondary" onClick={onCancel}>Stop</button>
      )}
    </section>
  );
}

function NoBridge() {
  return (
    <div className="page">
      <section className="section">
        <div className="section-head">
          <h2>Setup</h2>
        </div>
        <p className="lede">
          Setup from the app needs the local server: start the app with <code>npm run dev</code> in the <code>web</code> folder. This copy is a static
          build, so use the command line instead:
        </p>
        <pre className="log">{`python -m sleep_report auth             # sign in with Google
python -m sleep_report fetch --days 90  # download data
python -m sleep_report setup            # age and schedule
python -m sleep_report export           # rebuild the report`}</pre>
      </section>
    </div>
  );
}
