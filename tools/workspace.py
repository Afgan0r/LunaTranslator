"""Explicit workspace build, migration and launch commands."""

import argparse
from pathlib import Path

from workspace_build import build, launch
from workspace_migrate import migrate

REPO = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    assemble = commands.add_parser("build", help="Assemble offline; does not launch or touch .local")
    assemble.add_argument("--runtime-template", type=Path)
    assemble.add_argument("--native-dir", type=Path)
    assemble.add_argument("--hook-dir", type=Path)
    move = commands.add_parser("migrate", help="Copy legacy state once; source remains intact")
    move.add_argument("--legacy-home", type=Path, required=True)
    move.add_argument("--game-exe", type=Path)
    commands.add_parser("launch", help="Launch existing dist without building")
    args = parser.parse_args()
    try:
        if args.command == "build":
            build(REPO, args.runtime_template, args.native_dir, args.hook_dir)
            print("Workspace built. Previous runtime retained under build/runtime-backups.")
        elif args.command == "migrate":
            migrate(REPO, args.legacy_home, args.game_exe)
            print("Workspace migrated; legacy source remains intact.")
        else:
            launch(REPO)
    except (OSError, ValueError) as error:
        # Paths/settings can be private; expose only our controlled validation
        # messages, never raw filesystem exceptions or JSON payloads.
        parser.exit(1, "Workspace operation failed. " + (str(error) if type(error) is ValueError else "Check filesystem access and close Luna.") + "\n")


if __name__ == "__main__":
    main()
