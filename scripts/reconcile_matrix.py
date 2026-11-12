"""Independent reconciliation of the QA campaign CSV (read-only)."""
import collections
import csv
import os
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "reports", "qa-campaign", "test-matrix.csv")

with open(PATH, encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))

print(f"file: {PATH}")
print(f"rows (execution records): {len(rows)}")

scenarios = collections.OrderedDict()
for row in rows:
    scenarios.setdefault(row["test_id"], []).append(row)
print(f"unique test_ids (scenarios): {len(scenarios)}")

runs = collections.Counter(len(v) for v in scenarios.values())
print(f"runs-per-scenario distribution: {dict(runs)}")
odd = {k: len(v) for k, v in scenarios.items() if len(v) != 3}
print(f"scenarios not executed exactly 3x: {odd or 'none'}")

print("\nstatus counts (raw rows):")
for status, count in sorted(collections.Counter(r["status"] for r in rows).items()):
    print(f"  {status}: {count}")
print(f"  TOTAL: {sum(collections.Counter(r['status'] for r in rows).values())}")

print("\ntest_type counts:")
for t, count in sorted(collections.Counter(r["test_type"] for r in rows).items()):
    print(f"  {t}: {count}")

print("\nfeature areas:", len({r["feature"] for r in rows}))
for feature, count in sorted(collections.Counter(r["feature"] for r in rows).items()):
    print(f"  {feature}: {count}")

seen = collections.Counter(tuple(sorted(r.items())) for r in rows)
dupes = [k for k, v in seen.items() if v > 1]
print(f"\nidentical duplicate rows: {len(dupes)}")

missing_runs = []
for test_id, entries in scenarios.items():
    numbers = sorted(int(e["run_number"]) for e in entries)
    if numbers != [1, 2, 3]:
        missing_runs.append((test_id, numbers))
print(f"scenarios with missing/odd run numbers: {missing_runs or 'none'}")

empty = [r["test_id"] for r in rows if not r["actual_result"].strip()]
print(f"rows without an actual_result: {empty or 'none'}")

print("\nper-scenario status breakdown:")
for test_id, entries in scenarios.items():
    statuses = sorted({e["status"] for e in entries})
    print(f"  {test_id:<8} runs={len(entries)} statuses={statuses} feature={entries[0]['feature']}")
