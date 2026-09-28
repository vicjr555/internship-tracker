"""Copy all app data from one database to another (e.g. Render PostgreSQL -> Neon).

Run from the project root with the virtualenv active:

    python scripts/copy_database.py

It asks for the SOURCE and TARGET database URLs (paste them in; they are not saved),
then:
  1. dumps every app table from the source to backups/<timestamp>.json,
  2. creates the tables in the target (migrate),
  3. loads the dump into the target,
  4. prints row counts from both so you can check they match.

The target should be a new, empty database.
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "backups"

# Tables Django fills in by itself during migrate, or that aren't worth copying.
EXCLUDE = ["contenttypes", "auth.permission", "sessions", "admin.logentry"]

COUNT_SCRIPT = (
    "from django.contrib.auth.models import User;"
    "from listings.models import Listing, SyncRun;"
    "from applications.models import Application, StatusChange;"
    "print({'users': User.objects.count(), 'listings': Listing.objects.count(),"
    " 'applications': Application.objects.count(), 'status_changes': StatusChange.objects.count(),"
    " 'sync_runs': SyncRun.objects.count()})"
)


def manage(database_url, *args):
    """Run `manage.py <args>` against the given database. Stops the script on failure."""
    # PYTHONUTF8=1: on Windows, dumpdata would otherwise write the file in the local
    # code page (e.g. cp1252) and loaddata, which reads UTF-8, would fail on "–" etc.
    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONUTF8": "1"}
    result = subprocess.run([sys.executable, "manage.py", *args], cwd=ROOT, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout, result.stderr, sep="\n")
        sys.exit(f"manage.py {args[0]} failed; nothing further was done.")
    return result.stdout.strip()


def ask(prompt):
    url = input(prompt).strip().strip('"').strip("'")
    if "://" not in url:
        sys.exit("That doesn't look like a database URL (expected something like postgresql://...).")
    return url


def main():
    source = ask("SOURCE database URL (Render 'External Database URL'): ")
    target = ask("TARGET database URL (Neon connection string): ")
    if source == target:
        sys.exit("Source and target are the same database.")

    BACKUP_DIR.mkdir(exist_ok=True)
    backup = BACKUP_DIR / f"backup-{datetime.now():%Y%m%d-%H%M%S}.json"

    print("1/4 Dumping source data...")
    excludes = [arg for name in EXCLUDE for arg in ("-e", name)]
    manage(source, "dumpdata", "--natural-foreign", "--natural-primary", *excludes, "-o", str(backup))
    print(f"    Saved {backup.stat().st_size / 1_000_000:.1f} MB to {backup.relative_to(ROOT)}")

    print("2/4 Creating tables in target...")
    manage(target, "migrate", "--no-input")

    print("3/4 Loading data into target...")
    print("    " + manage(target, "loaddata", str(backup)))

    print("4/4 Comparing row counts...")
    source_counts = manage(source, "shell", "-c", COUNT_SCRIPT).splitlines()[-1]
    target_counts = manage(target, "shell", "-c", COUNT_SCRIPT).splitlines()[-1]
    print(f"    source: {source_counts}")
    print(f"    target: {target_counts}")
    if source_counts == target_counts:
        print("\nDone: counts match. Now set DATABASE_URL on Render to the TARGET URL.")
    else:
        sys.exit("\nCounts differ. Don't switch yet; something went wrong.")


if __name__ == "__main__":
    main()
