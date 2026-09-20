from pathlib import Path
import subprocess

EXPECTED_CONFLICTS = {
    "CheckRoyalCaribbeanPrice.py",
    "docs/watchlist-addons.md",
    "docs/watchlist-cruise-url.md",
    "unittests/test_cabin_availability.py",
    "unittests/test_price_alert_exclusions.py",
}

def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True)

conflicts = set(
    run("git", "diff", "--name-only", "--diff-filter=U").stdout.splitlines()
)
if conflicts != EXPECTED_CONFLICTS:
    raise SystemExit(f"Unexpected conflict set: {sorted(conflicts)}")

subprocess.run(
    [
        "git", "checkout", "--theirs", "--",
        "docs/watchlist-addons.md",
        "docs/watchlist-cruise-url.md",
        "unittests/test_cabin_availability.py",
        "unittests/test_price_alert_exclusions.py",
    ],
    check=True,
)

path = Path("CheckRoyalCaribbeanPrice.py")
lines = path.read_text().splitlines(keepends=True)
out = []
i = 0
count = 0
while i < len(lines):
    if not lines[i].startswith("<<<<<<< "):
        out.append(lines[i])
        i += 1
        continue
    count += 1
    i += 1
    while i < len(lines) and not lines[i].startswith("======="):
        i += 1
    if i >= len(lines):
        raise SystemExit("unterminated conflict before separator")
    i += 1
    theirs = []
    while i < len(lines) and not lines[i].startswith(">>>>>>> "):
        theirs.append(lines[i])
        i += 1
    if i >= len(lines):
        raise SystemExit("unterminated conflict after separator")
    out.extend(theirs)
    i += 1
if count == 0:
    raise SystemExit("expected checker conflict blocks")
path.write_text("".join(out))
print(f"Resolved {count} checker conflict blocks in favor of upstream")

subprocess.run(
    [
        "git", "add",
        "CheckRoyalCaribbeanPrice.py",
        "docs/watchlist-addons.md",
        "docs/watchlist-cruise-url.md",
        "unittests/test_cabin_availability.py",
        "unittests/test_price_alert_exclusions.py",
    ],
    check=True,
)

remaining = run("git", "diff", "--name-only", "--diff-filter=U").stdout.strip()
if remaining:
    raise SystemExit("Unresolved conflicts remain:\n" + remaining)

baseline_path = Path("UPSTREAM-BASELINE.md")
baseline = baseline_path.read_text()
baseline = baseline.replace(
    "Baseline commit: `c3863a148118b386a54c837bf5fcedd8b3027ef1`",
    "Baseline commit: `ac7e426931c12ef21ccd2badb223b04046c0a860`",
)
baseline = baseline.replace(
    "Commit subject: Merge pull request #122 from tecmage/fix-final-payment-market",
    "Commit subject: Merge pull request #129 from uberswimmer/upstream/cabin-transition-alerts",
)
baseline_path.write_text(baseline)

review_path = Path("AVAILABILITY-REVIEW.md")
review = review_path.read_text()
section_lines = [
    "",
    "## Upstream adoption sync through PR #129",
    "",
    "Upstream `main` through `ac7e426931c12ef21ccd2badb223b04046c0a860` is",
    "reconciled into the fork. Upstream is now authoritative for the functionality",
    "accepted in PRs #127-129: authenticated-session cleanup after profile failure,",
    "reservation-scoped `ignoredPriceAlerts`, and prospective cabin availability",
    "transition alerts.",
    "",
    "For cabin alerts, the fork intentionally adopts upstream's editable JSON state",
    "implementation and readable search keys. The prior fork used SQLite for",
    "`cabinAvailabilityStateFile`; that file is not migrated. A fresh JSON state may",
    "therefore send one initial alert for a cabin that is already available, which is an",
    "accepted transition behavior. Price-history SQLite and reservation-availability",
    "state remain separate and unchanged.",
    "",
    "The sync also includes upstream Browse/PhonePriceCheck/userscript hardening,",
    "documentation and gitignore privacy fixes, release-build ordering fixes, and",
    "test-suite robustness changes. Fork-only entertainment/dining availability,",
    "scheduled checks, calendar/report exports, web run controls, and the dedicated",
    "GHCR publishing workflow remain in place. The onboard-activity feature PR stays",
    "separate for rebase and retest after this sync.",
    "",
]
if "## Upstream adoption sync through PR #129" not in review:
    review += "\n".join(section_lines)
review_path.write_text(review)

source = path.read_text()
required = [
    "class AvailabilityWatch",
    "def process_availability_bookings",
    "def parse_calendar_config",
    "def run_availability_only",
    "cabin_state_lock",
    "ignoredPriceAlerts",
    "data/cabin-availability.json",
]
missing = [needle for needle in required if needle not in source]
if missing:
    raise SystemExit("Missing reconciled capabilities: " + ", ".join(missing))

active_paths = [
    Path("CheckRoyalCaribbeanPrice.py"),
    Path("README.md"),
    Path("SAMPLE-config.yaml"),
    Path("AVAILABILITY-SETUP.md"),
    Path("GITHUB-DEPLOYMENT.md"),
    Path("LOCAL-WEB-SETUP.md"),
]
active_paths.extend(Path("docs").glob("*.md"))
stale = []
for candidate in active_paths:
    if candidate.exists() and "cabin-availability.sqlite3" in candidate.read_text(errors="ignore"):
        stale.append(str(candidate))
if stale:
    raise SystemExit("Stale cabin SQLite references: " + ", ".join(stale))

subprocess.run(["git", "add", "UPSTREAM-BASELINE.md", "AVAILABILITY-REVIEW.md"], check=True)
