"""Personal settings that decide which reference ranges and findings apply: settings.json.

    {
      "age": 34,                     years; picks age-appropriate ranges (14 and over). null = adult ranges
      "days_off": ["Sat", "Sun"],    days without work/school; the nights before them are "free nights"
      "usual_bedtime": "23:00",      the bedtime your schedule asks of you; late timing is measured from it
      "shift_work": false,           true skips the late-timing and social-jetlag findings
      "often_tired": null,           true/false; false hides the "tired despite normal oxygen" note
      "device": "google"             "google" (Fitbit, Pixel Watch) or "apple" (Apple Watch): picks the setup steps
    }
"""
import json
import sys

from .store import HOME

SETTINGS_FILE = HOME / "settings.json"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DEFAULTS = {"age": None, "days_off": ["Sat", "Sun"], "usual_bedtime": "23:00", "shift_work": False, "often_tired": None,
            "device": "google"}

# The age groups used by the National Sleep Foundation's duration and quality recommendations.
GROUPS = [
    ("teen", 14, 17, "teenagers (14-17)"),
    ("young_adult", 18, 25, "young adults (18-25)"),
    ("adult", 26, 64, "adults (26-64)"),
    ("older", 65, 200, "older adults (65 and over)"),
]


def load(path=SETTINGS_FILE):
    """Settings merged over the defaults; exits with a clear message on bad values."""
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    s = {**DEFAULTS, **raw}
    problems = validate(s)
    if problems:
        sys.exit(f"Problem in {path}:\n  " + "\n  ".join(problems))
    return s


def save(values, path=SETTINGS_FILE):
    """Validate and write settings; raises ValueError listing every problem."""
    s = {**DEFAULTS, **{k: v for k, v in values.items() if k in DEFAULTS}}
    problems = validate(s)
    if problems:
        raise ValueError("; ".join(problems))
    path.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
    return s


def validate(s):
    """List of problems with a settings dict (empty when it's fine)."""
    problems = []
    if s["age"] is not None and (not isinstance(s["age"], int) or not 0 < s["age"] < 120):
        problems.append('"age" must be a whole number of years, or null')
    elif s["age"] is not None and s["age"] < 14:
        problems.append("this report's reference ranges start at age 14")
    if not isinstance(s["days_off"], list) or any(d not in DAYS for d in s["days_off"]):
        problems.append(f'"days_off" must be a list of {", ".join(DAYS)}')
    try:
        bedtime_h(s["usual_bedtime"])
    except (ValueError, AttributeError):
        problems.append('"usual_bedtime" must look like "23:00"')
    for key in ("shift_work",):
        if not isinstance(s[key], bool):
            problems.append(f'"{key}" must be true or false')
    if s["often_tired"] not in (True, False, None):
        problems.append('"often_tired" must be true, false or null')
    if s["device"] not in ("google", "apple"):
        problems.append('"device" must be "google" or "apple"')
    return problems


def bedtime_h(text):
    """"23:00" -> hours after 18:00 (5.0); "01:30" -> 7.5."""
    h, m = (int(x) for x in text.split(":"))
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(text)
    return (h - 18) % 24 + m / 60


def free_evenings(days_off):
    """Days off -> the evenings before them (a night before Saturday starts on Friday evening)."""
    return {DAYS[(DAYS.index(d) - 1) % 7] for d in days_off}


def profile(s):  # the data source is added by the caller (store.load_source)
    """What the report should know about the person, for the literature engine and the app."""
    group = next((g for g in GROUPS if s["age"] is not None and g[1] <= s["age"] <= g[2]), None)
    assumed = group is None
    group = group or GROUPS[2]  # no age given: adult ranges
    return {
        "age": s["age"],
        "group": group[0],
        "groupLabel": group[3],
        "ageAssumed": assumed,
        "daysOff": s["days_off"],
        "usualBedtime": s["usual_bedtime"],
        "usualBedtimeH": bedtime_h(s["usual_bedtime"]),
        "shiftWork": s["shift_work"],
        "oftenTired": s["often_tired"],
    }


def setup(path=SETTINGS_FILE):
    """Ask the questions and write settings.json."""
    current = load(path)
    print("A few questions so the report uses the right reference ranges. Press Enter to keep [the current value].\n")

    def ask(question, default, parse):
        while True:
            answer = input(f"{question} [{default}]: ").strip()
            if not answer:
                return parse(str(default)) if default not in (None, "") else None
            try:
                return parse(answer)
            except ValueError as e:
                print(f"  {e}")

    def age(text):
        if text.lower() in ("none", "skip", "-"):
            return None
        n = int(text)
        if not 14 <= n < 120:
            raise ValueError("enter an age of 14 or over, or 'skip'")
        return n

    def days(text):
        out = [d.strip().title()[:3] for d in text.replace(",", " ").split()]
        if any(d not in DAYS for d in out):
            raise ValueError(f"use day names like {' '.join(DAYS)}")
        return out

    def clock(text):
        bedtime_h(text)
        return text if len(text) == 5 else f"{int(text.split(':')[0]):02d}:{text.split(':')[1]}"

    def yes_no(text):
        t = text.lower()
        if t in ("y", "yes", "true"):
            return True
        if t in ("n", "no", "false"):
            return False
        if t in ("skip", "none", "-"):
            return None
        raise ValueError("answer y or n")

    new = {
        "device": current["device"],
        "age": ask("Your age in years (or 'skip')", current["age"] or "skip", age),
        "days_off": ask("Your usual days off, e.g. 'Sat Sun'", " ".join(current["days_off"]), days),
        "usual_bedtime": ask("The bedtime your schedule asks of you, e.g. 23:00", current["usual_bedtime"], clock),
        "shift_work": ask("Do you work night or rotating shifts? (y/n)", "y" if current["shift_work"] else "n", yes_no),
        "often_tired": ask("Are you often tired during the day? (y/n/skip)",
                           {True: "y", False: "n", None: "skip"}[current["often_tired"]], yes_no),
    }
    path.write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
    load(path)  # validate
    print(f"\nSaved {path}. Run  python -m sleep_report export  to update the report.")
