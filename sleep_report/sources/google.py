"""Source for Fitbit and Pixel Watch: Google sign-in and downloading from the Google Health API."""
import json
import secrets
import socket
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from ..store import ROOT, num, save_heart_rate, session_key, to_local

CLIENT_FILE = ROOT / "client_secret.json"
TOKEN_FILE = ROOT / "token.json"

SPO2_SCOPE = "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly"
SLEEP_SCOPE = "https://www.googleapis.com/auth/googlehealth.sleep.readonly"
REDIRECT = "http://localhost:8080/"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://health.googleapis.com/v4/users/me/dataTypes"


# ---------------------------------------------------------------- auth

def load_client():
    if not CLIENT_FILE.exists():
        sys.exit(f"Missing {CLIENT_FILE}\nDownload the OAuth client JSON from Google Cloud "
                 "(APIs & Services > Credentials) and save it under that name.")
    raw = json.loads(CLIENT_FILE.read_text())
    return raw.get("web") or raw.get("installed") or raw


def save_token(tok):
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600)
    TOKEN_FILE.write_text(json.dumps(tok, indent=2))


def sign_in():
    client = load_client()
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urlencode({
        "client_id": client["client_id"],
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": f"{SPO2_SCOPE} {SLEEP_SCOPE}",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if "code" in query or "error" in query:
                result.update({k: v[0] for k, v in query.items()})
                self.wfile.write(b"<h2>Done - you can close this tab.</h2>")
                done.set()

        def log_message(self, *_):
            pass

    class Server6(HTTPServer):
        address_family = socket.AF_INET6

    # Browsers may resolve "localhost" to 127.0.0.1 or ::1, so listen on both.
    done = threading.Event()
    servers = []
    for cls, host in ((HTTPServer, "127.0.0.1"), (Server6, "::1")):
        try:
            servers.append(cls((host, 8080), Handler))
        except OSError:
            pass
    if not servers:
        sys.exit("Port 8080 is in use by another program - close it and try again.")
    for s in servers:
        threading.Thread(target=s.serve_forever, daemon=True).start()

    def read_pasted():
        # Fallback when the redirect can't reach us: user pastes the address bar URL.
        line = sys.stdin.readline()
        if not line:
            return  # no input to read (run in the background): keep waiting for the browser
        query = parse_qs(urlparse(line.strip()).query)
        if "code" in query or "error" in query:
            result.update({k: v[0] for k, v in query.items()})
        done.set()
    threading.Thread(target=read_pasted, daemon=True).start()

    print("Opening your browser to sign in. If it doesn't open, paste this URL:\n" + url)
    print("\nIf Google warns the app isn't verified, click 'Continue'. If the browser ends on an\n"
          "error page at localhost:8080, copy the whole address bar URL, paste it here, press Enter.")
    webbrowser.open(url)
    while not done.wait(0.5):
        pass
    for s in servers:
        s.shutdown()
        s.server_close()

    if "error" in result:
        sys.exit(f"Sign-in failed: {result['error']}")
    if "code" not in result:
        sys.exit("No sign-in code in what was pasted - run auth again and paste the full URL.")
    if result.get("state") != state:
        sys.exit("Sign-in failed: state mismatch, try again.")

    resp = requests.post(TOKEN_URL, data={
        "code": result["code"],
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "redirect_uri": REDIRECT,
        "grant_type": "authorization_code",
    })
    if not resp.ok:
        sys.exit(f"Token exchange failed: {resp.status_code} {resp.text}")
    save_token({**resp.json(), "signed_in_at": time.time()})
    granted = granted_scopes()
    print(f"Signed in. Access to SpO2: {'yes' if SPO2_SCOPE in granted else 'NO'}, "
          f"sleep: {'yes' if SLEEP_SCOPE in granted else 'NO'}")
    if not {SPO2_SCOPE, SLEEP_SCOPE} <= granted:
        print("Run auth again and tick every checkbox on Google's consent screen.")


def granted_scopes():
    if not TOKEN_FILE.exists():
        return set()
    return set(json.loads(TOKEN_FILE.read_text()).get("scope", "").split())


def access_token():
    if not TOKEN_FILE.exists():
        sys.exit("Not signed in yet. Run:  python -m sleep_report auth")
    tok = json.loads(TOKEN_FILE.read_text())
    if tok.get("expires_at", 0) > time.time() + 60:
        return tok["access_token"]

    client = load_client()
    resp = requests.post(TOKEN_URL, data={
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "refresh_token": tok["refresh_token"],
        "grant_type": "refresh_token",
    })
    if not resp.ok:
        # Apps in "Testing" mode get refresh tokens that die after 7 days.
        sys.exit(f"Token refresh failed ({resp.status_code}). Sign in again with:  python -m sleep_report auth")
    new = resp.json()
    new.setdefault("refresh_token", tok["refresh_token"])
    new.setdefault("scope", tok.get("scope", ""))
    if "signed_in_at" in tok:
        new.setdefault("signed_in_at", tok["signed_in_at"])
    save_token(new)
    return new["access_token"]


# ---------------------------------------------------------------- fetch

def time_filter(field, start, end):
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return f'{field} >= "{start.strftime(fmt)}" AND {field} < "{end.strftime(fmt)}"'


def list_points(token, data_type, filt, page_size):
    params = {"filter": filt, "pageSize": page_size}
    while True:
        for attempt in range(5):
            resp = requests.get(f"{API}/{data_type}/dataPoints", params=params,
                                headers={"Authorization": f"Bearer {token}"})
            # rate limits and temporary server errors: wait and try again
            if resp.status_code not in (429, 500, 502, 503, 504) or attempt == 4:
                break
            time.sleep(2 ** attempt * 2)
        if not resp.ok:
            hint = ""
            if resp.status_code == 403:
                hint = ("\nCheck that the scope is added on the Data Access page, that you ticked it "
                        "when signing in, and that you've signed in to the Google Health app.")
            sys.exit(f"API error {resp.status_code} for {data_type}: {resp.text}{hint}")
        body = resp.json()
        yield from body.get("dataPoints", [])
        if not body.get("nextPageToken"):
            return
        params["pageToken"] = body["nextPageToken"]


def fetch_spo2(token, start, end, rows):
    """Add minute-level SpO2 readings to `rows`; returns how many were new."""
    before = len(rows)
    filt = time_filter("oxygen_saturation.sample_time.physical_time", start, end)
    for dp in list_points(token, "oxygen-saturation", filt, 10000):
        o = dp.get("oxygenSaturation")
        if not o:
            continue
        st = o["sampleTime"]
        utc = datetime.fromisoformat(st["physicalTime"]).astimezone(timezone.utc)
        local = to_local(st["physicalTime"], st.get("utcOffset"))
        rows[utc.isoformat()] = (local.isoformat(timespec="seconds"), float(o["percentage"]))
    return len(rows) - before


def fetch_sleep(token, start, end, sleeps):
    """Add Fitbit sleep sessions (stages, summary) to `sleeps`; returns how many were new."""
    before = len(sleeps)
    filt = time_filter("sleep.interval.end_time", start, end)
    for dp in list_points(token, "sleep", filt, 25):
        s = dp.get("sleep")
        if s:
            sleeps[dp.get("name") or s["interval"]["startTime"]] = s
    return len(sleeps) - before


def fetch_breathing(token, start, end, breathing):
    """Add per-sleep breathing-rate summaries to `breathing`; returns how many were new."""
    before = len(breathing)
    filt = time_filter("respiratory_rate_sleep_summary.sample_time.physical_time", start, end)
    for dp in list_points(token, "respiratory-rate-sleep-summary", filt, 1000):
        b = dp.get("respiratoryRateSleepSummary")
        if b:
            breathing[b["sampleTime"]["physicalTime"]] = b
    return len(breathing) - before


DAILY_TYPES = {
    # data type: (filter field, data point field)
    "daily-heart-rate-variability": ("daily_heart_rate_variability", "dailyHeartRateVariability"),
    "daily-resting-heart-rate": ("daily_resting_heart_rate", "dailyRestingHeartRate"),
    "daily-sleep-temperature-derivations": ("daily_sleep_temperature_derivations", "dailySleepTemperatureDerivations"),
}


def fetch_daily(token, start, end, daily):
    """Add Fitbit's per-day summaries (HRV, resting heart rate, sleep temperature) to
    `daily` as {date: {field: value}}; returns how many days gained values."""
    before = sum(len(v) for v in daily.values())
    for data_type, (filter_name, field) in DAILY_TYPES.items():
        filt = f'{filter_name}.date >= "{start:%Y-%m-%d}" AND {filter_name}.date < "{end + timedelta(days=1):%Y-%m-%d}"'
        for dp in list_points(token, data_type, filt, 1000):
            d = dp.get(field)
            if not d:
                continue
            day = "{year:04d}-{month:02d}-{day:02d}".format(**d["date"])
            row = daily.setdefault(day, {})
            if field == "dailyHeartRateVariability":
                row.update(hrv=num(d.get("averageHeartRateVariabilityMilliseconds")),
                           hrv_deep=num(d.get("deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds")),
                           nonrem_hr=num(d.get("nonRemHeartRateBeatsPerMinute")))
            elif field == "dailyRestingHeartRate":
                row.update(resting_hr=num(d.get("beatsPerMinute")))
            else:
                row.update(temp=num(d.get("nightlyTemperatureCelsius")), temp_baseline=num(d.get("baselineTemperatureCelsius")),
                           temp_sd=num(d.get("relativeNightlyStddev30dCelsius")))
    return sum(len(v) for v in daily.values()) - before


def fetch_heart_rate(token, sleeps, hr_dir):
    """Download heart rate (a reading every few seconds) for each sleep session that
    doesn't have a file in `hr_dir` yet. Returns how many sessions were downloaded."""
    hr_dir.mkdir(parents=True, exist_ok=True)
    fetched = 0
    for raw in sleeps:
        path = hr_dir / f"{session_key(raw)}.csv"
        if path.exists():
            continue
        iv = raw["interval"]
        start = datetime.fromisoformat(iv["startTime"]).astimezone(timezone.utc) - timedelta(minutes=5)
        end = datetime.fromisoformat(iv["endTime"]).astimezone(timezone.utc) + timedelta(minutes=5)
        rows = []
        for dp in list_points(token, "heart-rate", time_filter("heart_rate.sample_time.physical_time", start, end),
                              10000):
            h = dp.get("heartRate")
            if h:
                st = h["sampleTime"]
                local = to_local(st["physicalTime"], st.get("utcOffset"))
                rows.append((local.isoformat(timespec="seconds"), int(float(h["beatsPerMinute"]))))
        save_heart_rate(path, rows)
        fetched += 1
        print(f"  heart rate {fetched}: {iv['startTime'][:10]} ({len(rows)} readings)", end="\r")
    if fetched:
        print()
    return fetched
