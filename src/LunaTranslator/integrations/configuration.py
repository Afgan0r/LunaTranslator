"""Validated, isolated configuration for game integration profiles."""

import copy
import json
import os
import re
import tempfile
from pathlib import Path

from .engine import TranslationError
from .transport import ALLOWED_MODELS


class Workspace:
    def __init__(self, home):
        self.home = Path(home)
        if not self.home.is_absolute():
            raise TranslationError("configuration", "Workspace home must be absolute.")
        self.config_path = self.home / "config.json"

    @staticmethod
    def _uid(uid):
        if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", uid):
            raise TranslationError("configuration", "Invalid profile identifier.")
        return uid

    def _load(self):
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            if (not isinstance(data, dict) or type(data.get("schema")) is not int
                    or data["schema"] != 1 or not isinstance(data.get("defaults"), dict)
                    or not isinstance(data.get("profiles"), dict)):
                raise ValueError
            return data
        except (OSError, ValueError, TypeError, TranslationError):
            raise TranslationError("configuration", "Invalid workspace configuration.") from None

    def _profile(self, data, uid):
        uid = self._uid(uid)
        if uid not in data["profiles"]:
            return None
        profile = data["profiles"][uid]
        if (not isinstance(profile, dict) or not isinstance(profile.get("adapter"), str)
                or not profile["adapter"] or not isinstance(profile.get("game_exe"), str)
                or not Path(profile["game_exe"]).is_absolute()
                or not isinstance(profile.get("settings"), dict)):
            raise TranslationError("configuration", "Invalid integration profile.")
        return profile

    def profile_home(self, uid):
        return self.home / "games" / self._uid(uid)

    def settings_for(self, uid):
        data = self._load()
        profile = self._profile(data, uid)
        if profile is None:
            raise TranslationError("configuration", "Unknown integration profile.")

        def merge(base, override):
            result = copy.deepcopy(base)
            for key, value in override.items():
                if isinstance(value, dict) and isinstance(result.get(key), dict):
                    result[key] = merge(result[key], value)
                else:
                    result[key] = copy.deepcopy(value)
            return result

        result = merge(data["defaults"], profile["settings"])
        result["game_exe"] = profile["game_exe"]
        return result

    def profile_for_game(self, uid, gamepath):
        uid = self._uid(uid)
        profile = self._profile(self._load(), uid)
        if profile is None:
            return None
        try:
            path = Path(gamepath)
            if not path.is_absolute():
                return None
            if os.path.normcase(str(path.resolve())) != os.path.normcase(str(Path(profile["game_exe"]).resolve())):
                return None
        except (OSError, TypeError, ValueError):
            return None
        return copy.deepcopy(profile)

    def set_model(self, uid, model, effort):
        uid = self._uid(uid)
        if model not in ALLOWED_MODELS or effort not in ("low", "medium", "high"):
            raise TranslationError("configuration", "Invalid model or reasoning effort.")
        data = self._load()
        profile = self._profile(data, uid)
        if profile is None:
            raise TranslationError("configuration", "Unknown integration profile.")
        profile["settings"]["model"] = model
        profile["settings"]["reasoning_effort"] = effort
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.home,
                                             delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.config_path)
        except OSError:
            raise TranslationError("configuration", "Could not save workspace configuration.") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
