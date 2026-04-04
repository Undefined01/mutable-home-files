import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mutable_file_runtime.core import load_task_file, reconcile_entry


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--home-directory")
    args = parser.parse_args(argv)

    payload = load_task_file(args.task_file)
    home_directory = args.home_directory or str(Path.home())

    for entry in payload["entries"]:
        reconcile_entry(entry, home_directory=home_directory)

    summary = {
        "entry_count": len(payload["entries"]),
        "targets": [entry["target"] for entry in payload["entries"]],
        "home_directory": home_directory,
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
