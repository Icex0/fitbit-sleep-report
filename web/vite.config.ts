import { join, resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { sleepReportApi } from "./api-plugin";

export default defineConfig({
  plugins: [react(), sleepReportApi()],
  // SLEEP_REPORT_HOME: serve that person's report (written to <home>/public/data by python -m sleep_report export)
  publicDir: process.env.SLEEP_REPORT_HOME ? join(resolve(process.env.SLEEP_REPORT_HOME), "public") : "public",
  server: { host: "127.0.0.1", port: 5173 },
  preview: { host: "127.0.0.1", port: 4173 },
});
