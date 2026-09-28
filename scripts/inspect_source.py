"""Phase 1 helper: download the SimplifyJobs listings JSON and summarize its schema.

Run with:  python scripts/inspect_source.py
Uses only the standard library so it works before any dependencies are installed.
"""

import json
import urllib.request
from collections import Counter, defaultdict

SOURCE_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/"
    "dev/.github/scripts/listings.json"
)


def type_name(value):
    if value is None:
        return "null"
    if isinstance(value, list):
        inner = {type_name(v) for v in value} or {"empty"}
        return f"list[{'|'.join(sorted(inner))}]"
    return type(value).__name__


def main():
    with urllib.request.urlopen(SOURCE_URL, timeout=30) as response:
        print("HTTP status:", response.status)
        print("ETag:", response.headers.get("ETag"))
        print("Content-Length:", response.headers.get("Content-Length"))
        listings = json.load(response)

    print("\nTop-level type:", type(listings).__name__)
    print("Total listings:", len(listings))

    print("\n--- Sample entries ---")
    for entry in listings[:2] + listings[-1:]:
        print(json.dumps(entry, indent=2))

    # Field presence and types across every entry.
    presence = Counter()
    types = defaultdict(Counter)
    for entry in listings:
        for key, value in entry.items():
            presence[key] += 1
            types[key][type_name(value)] += 1

    print("\n--- Fields (present in N of total, observed types) ---")
    for key in sorted(presence):
        type_summary = ", ".join(f"{t}×{n}" for t, n in types[key].most_common())
        print(f"{key:24} {presence[key]:>6}/{len(listings)}  {type_summary}")

    # Uniqueness checks for candidate ID fields.
    print("\n--- Uniqueness ---")
    for key in ("id", "url"):
        values = [e.get(key) for e in listings]
        print(f"{key}: {len(set(values))} unique of {len(values)}")

    # Status / categorical fields.
    print("\n--- Value distributions ---")
    for key in ("active", "is_visible", "source", "category", "sponsorship", "degrees", "terms"):
        if key not in presence:
            continue
        counter = Counter()
        for e in listings:
            value = e.get(key)
            if isinstance(value, list):
                counter.update(value)
            else:
                counter[json.dumps(value)] += 1
        print(f"{key}: {dict(counter.most_common(12))}")

    active_visible = sum(1 for e in listings if e.get("active") and e.get("is_visible", True))
    print("\nActive AND visible:", active_visible)


if __name__ == "__main__":
    main()
