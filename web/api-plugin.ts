// Local bridge between the web app and the Python tool (the sleep_report package), for the dev and preview servers.
//
// The app can't run Python itself, so these endpoints run a fixed set of sleep_report commands:
//   GET  /api/status            where setup stands (credentials, sign-in, data, settings)
//   GET  /api/job               the current or last long-running command and its output
//   POST /api/settings          save settings (validated by Python), then rebuild the report
//   POST /api/fetch {days}      download new data, then rebuild the report
//   POST /api/auth              sign in with Google (opens the browser)
//   POST /api/import-apple      upload an Apple Health export (raw body), import it, rebuild the report
//   POST /api/export            rebuild the report
//   POST /api/cancel            stop the running command
// Only requests from this app are accepted: POSTs must carry the X-Sleep-Report header (which
// a page on another site can't send without a CORS preflight that this server never approves),
// and the Host header must be localhost, against DNS rebinding.
import { spawn, type ChildProcess } from "node:child_process";
import { createWriteStream, rm } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const PYTHON = process.env.PYTHON ?? (process.platform === "win32" ? "python" : "python3");
const MAX_LOG = 40_000;

interface Job {
  id: number;
  kind: "auth" | "fetch" | "export" | "settings" | "import";
  status: "running" | "done" | "failed" | "cancelled";
  log: string;
  started: string;
  finished?: string;
}

let job: Job | null = null;
let child: ChildProcess | null = null;
let nextId = 1;

function python(args: string[]) {
  return spawn(PYTHON, ["-m", "sleep_report", ...args], {
    cwd: ROOT,
    env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8", SLEEP_REPORT_APP: "1" },
    windowsHide: true,
  });
}

/** Run a short command to completion and collect its output. */
function runOnce(args: string[], input?: string): Promise<{ code: number; out: string }> {
  return new Promise((resolve) => {
    const p = python(args);
    let out = "";
    p.stdout.on("data", (d) => (out += d));
    p.stderr.on("data", (d) => (out += d));
    p.on("error", (e) => resolve({ code: -1, out: `Couldn't start Python (${PYTHON}): ${e.message}` }));
    p.on("close", (code) => resolve({ code: code ?? -1, out }));
    if (input !== undefined) p.stdin.end(input);
  });
}

/** Start a long-running job: several sleep_report commands in a row, output collected in job.log. */
function startJob(kind: Job["kind"], steps: string[][], timeoutMs = 30 * 60_000, onDone?: () => void): Job {
  if (job?.status === "running") throw new Error("Another task is still running.");
  const current: Job = { id: nextId++, kind, status: "running", log: "", started: new Date().toISOString() };
  job = current;
  const append = (text: string) => {
    current.log = (current.log + text).slice(-MAX_LOG);
  };
  (async () => {
    for (const step of steps) {
      append(`$ python -m sleep_report ${step.join(" ")}\n`);
      const code = await new Promise<number>((resolve) => {
        const p = python(step);
        child = p;
        // stdin stays open: `auth` reads a pasted URL from it as a fallback and would stop on EOF
        const timer = setTimeout(() => p.kill(), timeoutMs);
        p.stdout.on("data", (d) => append(String(d)));
        p.stderr.on("data", (d) => append(String(d)));
        p.on("error", (e) => {
          append(`Couldn't start Python (${PYTHON}): ${e.message}\n`);
          resolve(-1);
        });
        p.on("close", (c) => {
          clearTimeout(timer);
          resolve(c ?? -1);
        });
      });
      child = null;
      if (current.status === "cancelled") break;
      if (code !== 0) {
        current.status = "failed";
        break;
      }
    }
    if (current.status === "running") current.status = "done";
    current.finished = new Date().toISOString();
    onDone?.();
  })();
  return current;
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (d) => {
      body += d;
      if (body.length > 10_000) reject(new Error("Request too large"));
    });
    req.on("end", () => resolve(body));
    req.on("error", reject);
  });
}

function send(res: ServerResponse, status: number, data: unknown) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(data));
}

const LOCAL_HOST = /^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/;

async function handle(req: IncomingMessage, res: ServerResponse, next: () => void) {
  const url = new URL(req.url ?? "/", "http://localhost");
  if (!url.pathname.startsWith("/api/")) return next();
  if (!LOCAL_HOST.test(req.headers.host ?? "")) return send(res, 403, { error: "Only available on this computer." });
  if (req.method === "POST" && req.headers["x-sleep-report"] !== "1") return send(res, 403, { error: "Missing app header." });

  try {
    const route = `${req.method} ${url.pathname}`;
    if (route === "GET /api/status") {
      const { code, out } = await runOnce(["status", "--json"]);
      if (code !== 0) return send(res, 500, { error: out.trim() || "sleep_report status failed" });
      return send(res, 200, { status: JSON.parse(out), job });
    }
    if (route === "GET /api/job") return send(res, 200, { job });
    if (route === "POST /api/settings") {
      if (job?.status === "running") return send(res, 409, { error: "Another task is still running." });
      const { code, out } = await runOnce(["setup", "--stdin"], await readBody(req));
      if (code !== 0) return send(res, 400, { error: out.trim().replace(/^Settings not saved: /, "") });
      // ?rebuild=0 saves without rebuilding the report (e.g. choosing a device before there's data)
      const rebuild = url.searchParams.get("rebuild") !== "0";
      return send(res, 200, { settings: JSON.parse(out), job: rebuild ? startJob("settings", [["export"]]) : null });
    }
    if (route === "POST /api/fetch") {
      const { days } = JSON.parse((await readBody(req)) || "{}");
      if (!Number.isInteger(days) || days < 1 || days > 365) return send(res, 400, { error: "Days must be 1 to 365." });
      return send(res, 200, { job: startJob("fetch", [["fetch", "--days", String(days)], ["export"]]) });
    }
    if (route === "POST /api/auth") return send(res, 200, { job: startJob("auth", [["auth"]], 10 * 60_000) });
    if (route === "POST /api/import-apple") {
      if (job?.status === "running") return send(res, 409, { error: "Another task is still running." });
      // the export can be gigabytes: stream the raw body to a temporary file
      const file = join(tmpdir(), `sleep-report-apple-export-${Date.now()}.zip`);
      await new Promise<void>((resolve, reject) => {
        const out = createWriteStream(file);
        req.pipe(out);
        out.on("finish", () => resolve());
        out.on("error", reject);
        req.on("error", reject);
      });
      const replace = url.searchParams.get("replace") === "1" ? ["--replace"] : [];
      const cleanup = () => rm(file, { force: true }, () => undefined);
      return send(res, 200, { job: startJob("import", [["import-apple", file, ...replace], ["export"]], 30 * 60_000, cleanup) });
    }
    if (route === "POST /api/export") return send(res, 200, { job: startJob("export", [["export"]]) });
    if (route === "POST /api/cancel") {
      if (job?.status === "running") {
        job.status = "cancelled";
        child?.kill();
      }
      return send(res, 200, { job });
    }
    return send(res, 404, { error: "Unknown endpoint." });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return send(res, message.startsWith("Another task") ? 409 : 500, { error: message });
  }
}

export function sleepReportApi(): Plugin {
  return {
    name: "sleep-report-api",
    configureServer(server) {
      server.middlewares.use((req, res, next) => void handle(req, res, next));
    },
    configurePreviewServer(server) {
      server.middlewares.use((req, res, next) => void handle(req, res, next));
    },
  };
}
