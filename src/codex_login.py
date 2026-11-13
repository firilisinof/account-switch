"""Switch shared Codex logins or launch the CLI in a separate home."""

import argparse
import base64
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from typing import Iterator


class SwitchError(Exception):
    pass


def profile_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise argparse.ArgumentTypeError(
            "use 1-64 letters, digits, underscores, or hyphens, starting with a letter or digit"
        )
    return value


def identity(data: bytes) -> tuple[str, str]:
    try:
        auth = json.loads(data)
        tokens = auth["tokens"]
        if auth.get("auth_mode", "chatgpt") != "chatgpt":
            raise ValueError()
        for key in ("account_id", "id_token", "access_token", "refresh_token"):
            if not isinstance(tokens[key], str) or not tokens[key]:
                raise ValueError()
        payload = tokens["id_token"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if not isinstance(claims["sub"], str) or not claims["sub"]:
            raise ValueError()
        return tokens["account_id"], claims["sub"]
    except (KeyError, IndexError, TypeError, ValueError):
        raise SwitchError("Expected saved ChatGPT credentials. Sign in with `codex login`.") from None


def read_auth(path: Path) -> bytes:
    if path.is_symlink():
        raise SwitchError(f"Refusing credential symlink: {path}")
    data = path.read_bytes()
    identity(data)
    return data


def write_auth(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise SwitchError(f"Refusing credential symlink: {path}")
    fd, temporary = tempfile.mkstemp(prefix=".auth-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def processes() -> list[tuple[int, str]]:
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,comm="], capture_output=True, text=True, check=True
    )
    rows = [line.strip().split(None, 1) for line in result.stdout.splitlines() if line.strip()]
    return [(int(pid), command) for pid, command in rows]


def cli_processes(rows: list[tuple[int, str]], app: Path | None = None) -> list[int]:
    return [
        pid for pid, command in rows
        if Path(command).name in ("codex", "codex-cli")
        and (app is None or not command.startswith(str(app) + "/"))
    ]


def require_cli_closed(app: Path | None = None) -> None:
    pids = cli_processes(processes(), app)
    if pids:
        raise SwitchError(
            "Close Codex CLI sessions and app servers before switching "
            f"(PIDs: {', '.join(map(str, pids))}). Run this command in a normal terminal."
        )


def desktop_app() -> Path | None:
    for root in (Path("/Applications"), Path.home() / "Applications"):
        for name in ("ChatGPT.app", "Codex.app"):
            path = root / name
            info = path / "Contents/Info.plist"
            if info.exists():
                with info.open("rb") as stream:
                    if plistlib.load(stream).get("CFBundleIdentifier") == "com.openai.codex":
                        return path
    return None


def desktop_running(app: Path | None) -> bool:
    return app is not None and any(
        command.startswith(str(app) + "/Contents/MacOS/") for _, command in processes()
    )


def quit_desktop(app: Path) -> None:
    print("Closing the desktop app. Complete any quit dialog.", flush=True)
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", 'tell application id "com.openai.codex" to quit'],
            capture_output=True, text=True, timeout=35,
        )
    except subprocess.TimeoutExpired:
        raise SwitchError("Desktop did not quit. Credentials were not changed.") from None
    if result.returncode:
        raise SwitchError("Desktop rejected the quit request. Credentials were not changed.")
    deadline = time.monotonic() + 30
    while desktop_running(app):
        if time.monotonic() >= deadline:
            raise SwitchError("Desktop is still running. Credentials were not changed.")
        time.sleep(0.2)


class Profiles:
    def __init__(self, home: Path):
        self.home = home.expanduser().resolve()
        self.auth = self.home / "auth.json"
        self.directory = self.home / "account-switch"
        if self.directory.is_symlink():
            raise SwitchError(f"Refusing profile directory symlink: {self.directory}")
        config = self.home / "config.toml"
        settings = tomllib.loads(config.read_text()) if config.exists() else {}
        mode = settings.get("cli_auth_credentials_store", "file")
        if mode != "file":
            raise SwitchError(
                f"Credential storage is {mode!r}. This tool requires "
                '`cli_auth_credentials_store = "file"` in config.toml.'
            )

    def path(self, name: str) -> Path:
        return self.directory / f"{name}.json"

    def saved(self) -> dict[str, bytes]:
        return {p.stem: read_auth(p) for p in sorted(self.directory.glob("*.json"))}

    def current(self) -> bytes | None:
        return read_auth(self.auth) if self.auth.exists() or self.auth.is_symlink() else None

    def match(self, data: bytes | None) -> str | None:
        if data is None:
            return None
        account = identity(data)
        return next(
            (name for name, saved in self.saved().items() if identity(saved) == account),
            None,
        )

    @contextmanager
    def lock(self) -> Iterator[None]:
        if not self.home.is_dir():
            raise SwitchError(f"Codex home does not exist: {self.home}. Run `codex login` first.")
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.directory.chmod(0o700)
        fd = os.open(self.directory / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SwitchError("Another codex-login command is running.") from None
            yield

    def save(self, name: str, data: bytes) -> None:
        existing = self.match(data)
        if existing is not None and existing != name:
            raise SwitchError(f"This account is already saved as {existing!r}. Use `rename`.")
        destination = self.path(name)
        if destination.exists() and identity(read_auth(destination)) != identity(data):
            raise SwitchError(f"Profile {name!r} belongs to a different account.")
        write_auth(destination, data)

    def use(self, name: str) -> None:
        target = read_auth(self.path(name))
        current = self.current()
        if current is not None and identity(current) == identity(target):
            self.save(name, current)
            print(f"{name} is already active. Saved its latest credentials.")
            return
        if current is not None and self.match(current) is None:
            raise SwitchError("Save the current login first: codex-login account save NAME")
        app = desktop_app()
        require_cli_closed(app)
        restart = desktop_running(app)
        if restart:
            if self.home != (Path.home() / ".codex").resolve():
                raise SwitchError("Close the desktop app before switching a custom CODEX_HOME.")
            quit_desktop(app)
        try:
            require_cli_closed()
            # read again after all credential writers have stopped
            current = self.current()
            if current is not None:
                previous = self.match(current)
                if previous is None:
                    raise SwitchError("The active login changed. Save it with `save NAME` first.")
                self.save(previous, current)
            target = read_auth(self.path(name))
            write_auth(self.auth, target)
        except BaseException:
            if restart:
                print("Switch failed. Reopen the desktop app manually.", file=sys.stderr)
            raise
        print(f"Active profile: {name}. New Codex CLI sessions will use it.")
        if restart:
            result = subprocess.run(["/usr/bin/open", "-a", str(app)], check=False)
            if result.returncode:
                raise SwitchError(f"Profile {name!r} is active, but the desktop app could not reopen.")
            print("Reopened the desktop app with the selected login.")

    def login(self, name: str, device_auth: bool) -> None:
        current = self.current()
        if self.match(current) == name:
            raise SwitchError("Switch to another profile before renewing the active profile's login.")
        executable = shutil.which("codex")
        if executable is None:
            raise SwitchError("Cannot find `codex` on PATH.")
        with tempfile.TemporaryDirectory(prefix=".login-", dir=self.directory) as temporary:
            command = [executable, "-c", 'cli_auth_credentials_store="file"', "login"]
            if device_auth:
                command.append("--device-auth")
            result = subprocess.run(command, env={**os.environ, "CODEX_HOME": temporary}, cwd=temporary)
            if result.returncode:
                raise SwitchError("Login failed. The active profile was not changed.")
            self.save(name, read_auth(Path(temporary) / "auth.json"))
        print(f"Saved {name}. Activate it with: codex-login account switch {name}")


def cli_homes(root: Path) -> list[str]:
    return sorted(
        path.name for path in root.iterdir()
        if path.is_dir() and not path.is_symlink() and (path / "AGENTS.md").is_symlink()
    ) if root.is_dir() else []


def launch_cli(shared: Path, root: Path, name: str, arguments: list[str]) -> int:
    executable = shutil.which("codex")
    if executable is None:
        raise SwitchError("Cannot find `codex` on PATH.")
    home = root / name
    login = arguments in (["login"], ["login", "--device-auth"])
    if root.is_symlink() or home.is_symlink():
        raise SwitchError(f"Refusing symlink in CLI home path: {home}")
    bootstrap = shared / "AGENTS.md"
    if not bootstrap.is_file():
        raise SwitchError(f"Restore the wiki bootstrap at {bootstrap}.")
    if name not in cli_homes(root):
        if not login:
            available = ", ".join(cli_homes(root)) or "none"
            raise SwitchError(
                f"Unknown CLI home {name!r}. Available: {available}. "
                f"Set up with: codex-login cli {name} login"
            )
        root.mkdir(mode=0o700, exist_ok=True)
        home.mkdir(mode=0o700)
        (home / "AGENTS.md").symlink_to(bootstrap)
    if (home / "AGENTS.md").resolve() != bootstrap.resolve():
        raise SwitchError(f"Unexpected wiki bootstrap link in {home}.")
    profiles = Profiles(home)
    command = [executable, "-c", 'cli_auth_credentials_store="file"']
    with profiles.lock():
        current = profiles.current()
        if login:
            with tempfile.TemporaryDirectory(prefix=".login-", dir=home) as temporary:
                result = subprocess.call(
                    [*command, *arguments], env={**os.environ, "CODEX_HOME": temporary},
                )
                if result:
                    return result
                credentials = read_auth(Path(temporary) / "auth.json")
                if current is not None and identity(current) != identity(credentials):
                    raise SwitchError(f"CLI home {name!r} belongs to a different account.")
                write_auth(profiles.auth, credentials)
                return 0
        if current is None:
            raise SwitchError(f"Sign in first: codex-login cli {name} login")
        if arguments and arguments[0] in ("login", "logout"):
            raise SwitchError(f"Renew this login with: codex-login cli {name} login")
        return subprocess.call(
            [*command, *arguments], env={**os.environ, "CODEX_HOME": str(home)},
        )


def show_accounts(profiles: Profiles) -> list[str]:
    current = profiles.match(profiles.current())
    names = list(profiles.saved())
    for name in names:
        print(f"  {name}" + (" (active)" if name == current else ""))
    if current is None:
        print("  No saved account is active.")
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="group")
    commands.add_parser("list", help="show shared accounts and dedicated CLI homes")
    account = commands.add_parser("account", help="manage logins for the shared Codex home")
    accounts = account.add_subparsers(dest="command", required=True)
    accounts.add_parser("list", help="list saved shared accounts")
    for verb, help_text in (
        ("save", "save the current login under a name"),
        ("login", "add or renew a saved login"),
        ("switch", "switch the shared login and restart desktop if open"),
        ("remove", "delete an inactive saved login"),
        ("rename", "rename a saved login"),
    ):
        command = accounts.add_parser(verb, help=help_text)
        command.add_argument("name", type=profile_name)
        if verb == "login":
            command.add_argument("--device-auth", action="store_true")
        if verb == "rename":
            command.add_argument("new_name", type=profile_name)
    cli = commands.add_parser("cli", help="run Codex in a dedicated home")
    cli.add_argument("name", type=profile_name)
    cli.add_argument("codex_args", nargs=argparse.REMAINDER, help="arguments for Codex CLI")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise SwitchError("This version supports macOS only.")
    shared = Path.home() / ".codex"
    root = Path.home() / ".codex-cli"
    if args.group == "cli":
        sys.exit(launch_cli(shared, root, args.name, args.codex_args))
    profiles = Profiles(shared)
    if args.group in (None, "list"):
        print("Shared accounts")
        names = show_accounts(profiles)
        print("\nDedicated CLI homes")
        homes = cli_homes(root)
        for name in homes:
            print(f"  {name}")
        if not homes:
            print("  Set one up with: codex-login cli NAME login")
        print(f"\nSwitch: codex-login account switch {names[0] if names else 'NAME'}")
        print(f"Launch: codex-login cli {homes[0] if homes else 'NAME'}")
        return
    if args.command == "list":
        show_accounts(profiles)
        return
    with profiles.lock():
        if args.command == "save":
            data = profiles.current()
            if data is None:
                raise SwitchError("No active login. Run `codex login` first.")
            profiles.save(args.name, data)
            print(f"Saved current login as {args.name}.")
        elif args.command == "login":
            profiles.login(args.name, args.device_auth)
        elif args.command == "switch":
            profiles.use(args.name)
        elif args.command == "remove":
            if profiles.match(profiles.current()) == args.name:
                raise SwitchError("Cannot remove the active profile. Switch to another one first.")
            profiles.path(args.name).unlink()
            print(f"Removed {args.name}.")
        elif args.command == "rename":
            if profiles.path(args.new_name).exists():
                raise SwitchError(f"Profile {args.new_name!r} already exists.")
            profiles.path(args.name).rename(profiles.path(args.new_name))
            print(f"Renamed {args.name} to {args.new_name}.")


def cli() -> None:
    try:
        main()
    except (SwitchError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"codex-login: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCanceled.", file=sys.stderr)
        sys.exit(130)
