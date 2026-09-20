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

# Reconcile fork-only orchestration around upstream #127-129 behavior.
source = path.read_text()

old_cleanup = """                # A profile failure happens after login has created a live
                # session. This account will never enter the normal voyage
                # cleanup path or the deferred availability cleanup list.
                if account_info.access is not None:
                    account_info.access.session.close()
                continue
"""
new_cleanup = """                continue
"""
if source.count(old_cleanup) != 1:
    raise SystemExit(f"Expected exactly one obsolete post-notification cleanup block, found {source.count(old_cleanup)}")
source = source.replace(old_cleanup, new_cleanup, 1)

old_price_failure = """    if not rooms:
        log("Room price request failed" if results.get('price_check_failed')
            else "Room Price Not Found")
        # A pricing failure or absent fare does not erase inventory that the
        # room-selection endpoint already confirmed. Price mode records an
        # unknown/no-data result; availability mode can still report the
        # confirmed cabin with "Current price unavailable."
        if not results.get('price_check_failed'):
            results['room_available'] = False
        results['available_rooms'] = available_rooms
        return results
"""
new_price_failure = """    if not rooms:
        log("Room price request failed" if results.get('price_check_failed')
            else "Room Price Not Found")
        # Follow upstream #129: checkout price state is separate from the
        # room-selection inventory evidence stored in inventory_available.
        # Availability mode remaps that evidence before evaluating the alert.
        results['room_available'] = False
        results['available_rooms'] = available_rooms
        return results
"""
if source.count(old_price_failure) != 1:
    raise SystemExit(f"Expected exactly one legacy cabin price-failure block, found {source.count(old_price_failure)}")
source = source.replace(old_price_failure, new_price_failure, 1)

final_anchor = """        # Write the watchlist price results to JSON for external consumption
        if config.output_watch_as_json:
            write_watch_price_json(collected_watch_rows, config.output_json_watch_file)

        failure_summaries = []
"""
final_replacement = """        # Write the watchlist price results to JSON for external consumption
        if config.output_watch_as_json:
            write_watch_price_json(collected_watch_rows, config.output_json_watch_file)

        # Fork-only calendar/reservation-availability outputs must complete
        # before a deferred reservation-availability failure is surfaced.
        if calendar_export is not None:
            calendar_export.finish()

        if availability_error is not None:
            raise availability_error

        failure_summaries = []
"""
if source.count(final_anchor) != 1:
    raise SystemExit(f"Expected exactly one end-of-run finalization anchor, found {source.count(final_anchor)}")
source = source.replace(final_anchor, final_replacement, 1)

path.write_text(source)

# Verify upstream profile cleanup and fork deferred availability finalization both exist.
source = path.read_text()
integration_required = [
    'Session cleanup failed after profile lookup failure; continuing.',
    'failed_watches: List[int] = []',
    'availability_error = None',
    'finish_availability_run(config.availability, availability_found, availability_healthy)',
    'calendar_export.finish()',
    'if availability_error is not None:',
]
missing_integration = [needle for needle in integration_required if needle not in source]
if missing_integration:
    raise SystemExit("Missing integration behavior: " + ", ".join(missing_integration))

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

# Upstream docs/config.md currently carries one trailing space; keep the review
# branch diff-check clean without changing its wording.
config_doc = Path("docs/config.md")
config_lines = config_doc.read_text().splitlines()
config_doc.write_text("\n".join(line.rstrip() for line in config_lines) + "\n")
subprocess.run(["git", "add", "docs/config.md"], check=True)
