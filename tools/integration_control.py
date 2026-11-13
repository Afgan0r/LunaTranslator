"""Per-game local controls, without API requests or corpus-bearing status."""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src/LunaTranslator"))
from integrations.configuration import Workspace
from integrations.engine import Journal, TranslationError
from integrations.transport import ALLOWED_MODELS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=REPO / ".local")
    parser.add_argument("--game", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("retry")
    new_run = commands.add_parser("new-run")
    new_run.add_argument("--reason", default="New playthrough / older save loaded")
    model = commands.add_parser("select-model")
    model.add_argument("model", choices=ALLOWED_MODELS)
    model.add_argument("effort", choices=("low", "medium", "high"))
    args = parser.parse_args()
    try:
        workspace = Workspace(args.home)
        workspace.settings_for(args.game)
        if args.command == "select-model":
            workspace.set_model(args.game, args.model, args.effort)
            print("Model selected. Existing failures still require Retry.")
            return
        path = workspace.profile_home(args.game) / "journal.sqlite3"
        if not path.is_file():
            parser.exit(1, "No existing journal for this game.\n")
        with Journal(path) as journal:
            if args.command == "retry":
                print("Retry enabled." if journal.retry() else "No paused request to retry.")
            elif args.command == "new-run":
                print("New run:", journal.new_run(args.reason))
            else:
                print(json.dumps(journal.status(), indent=2))
    except (OSError, TranslationError):
        parser.exit(1, "Integration operation failed; verify workspace/profile and worker ownership.\n")


if __name__ == "__main__":
    main()
