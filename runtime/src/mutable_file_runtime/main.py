from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mutable_file_runtime.reconcile import reconcile_document
from mutable_file_runtime.task_schema import load_task_file



def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--home-directory")
    args = parser.parse_args(argv)

    task_file = load_task_file(args.task_file)
    home_directory = args.home_directory or str(Path.home())

    for document in task_file.documents:
        reconcile_document(document, home_directory=home_directory)

    summary = {
        "document_count": len(task_file.documents),
        "targets": [document.target for document in task_file.documents],
        "home_directory": home_directory,
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
