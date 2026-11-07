"""Private local controls. No game corpus or secrets appear in status."""

import argparse
import json
import sys
from pathlib import Path

tool_home = Path(__file__).resolve().parents[1]
code = tool_home / "src" / "LunaTranslator"
if not (code / "translator" / "grisaia").is_dir():
    code = tool_home / "runtime" / "LunaTranslator_x64" / "LunaTranslator"
sys.path.insert(0, str(code))
from translator.grisaia.engine import Journal
from translator.grisaia.transport import ALLOWED_MODELS, ClientConfig, ResponsesClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("retry")
    mark = sub.add_parser("new-run")
    mark.add_argument("--reason", default="New playthrough / older save loaded")
    sub.add_parser("preflight")
    choose = sub.add_parser("select-model")
    choose.add_argument("model", choices=ALLOWED_MODELS)
    choose.add_argument("effort", choices=["low", "medium"])
    args = parser.parse_args()
    path = args.home / "settings.json"
    if args.command == "preflight":
        # Egress can be tested before the production model is chosen.
        data = json.loads(path.read_text(encoding="utf-8"))
        proxy = data["proxy"]
        config = ClientConfig(key_file=data["key_file"], proxy_host=proxy["host"],
                              proxy_port=proxy["port"], expected_country=data["expected_country"],
                              model="gpt-5.6-terra", geo_host=data.get("geo_host", "ipapi.co"),
                              expected_region=data.get("expected_region"),
                              proxy_username=proxy.get("username"), proxy_password=proxy.get("password"))
        print(json.dumps(ResponsesClient(config).preflight(), ensure_ascii=False))
    elif args.command == "select-model":
        settings = json.loads(path.read_text(encoding="utf-8"))
        settings.update(model=args.model, reasoning_effort=args.effort)
        temporary = path.with_suffix(".new")
        temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        print("Model selected. Existing failures still require Retry.")
    else:
        with Journal(args.home / "journal.sqlite3") as journal:
            if args.command == "retry":
                print("Retry enabled." if journal.retry() else "No paused request to retry.")
            elif args.command == "new-run":
                print("New run:", journal.new_run(args.reason))
            else:
                print(json.dumps(journal.status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
