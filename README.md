# codex-login

Manage saved ChatGPT logins for the shared Codex home on macOS, or run Codex
CLI with a dedicated login. Requires Python 3.11+ and Codex CLI on PATH.

```sh
uv tool install ~/ws/codex-login
codex-login
```

After changing the source, reinstall with `uv tool install --reinstall ~/ws/codex-login`.

With no arguments, or with `list`, the tool shows shared accounts and dedicated
CLI homes.

## Nix

Call `package.nix` with `pkgs.callPackage` to build the CLI. For Home
Manager, add the package to `home.packages` using a pinned checkout of
this repository:

```nix
home.packages = [
  (pkgs.callPackage (codexLoginSource + "/package.nix") { })
];
```

`codexLoginSource` is the path to the pinned source, for example a
non-flake input. Install Codex separately so `codex` is on PATH.

## Shared accounts

```sh
codex-login account save personal
codex-login account login work
codex-login account switch work
codex-login account list
codex-login account rename work office
codex-login account remove office
```

`save` records the current ChatGPT login. `login` adds or renews an inactive
saved account and supports `--device-auth`. `switch` updates `~/.codex/auth.json`
and restarts the desktop app if open. Finish desktop tasks and close standalone
Codex CLI sessions and app servers before switching. Complete any desktop quit
dialog. Shared accounts use file-based auth. Existing saved logins remain in
`~/.codex/account-switch`.

## Dedicated CLI homes

```sh
codex-login cli work login
codex-login cli work
codex-login cli work resume
```

The first command creates `~/.codex-cli/work`, links its `AGENTS.md` to
`~/.codex/AGENTS.md`, and prompts for browser sign-in. Run it again to renew the
same account. A login for a different account requires a different home name.
Each home keeps its own local configuration and chat history. The name is
independent of saved shared accounts. The CLI can run alongside the desktop
app, which uses `~/.codex`.

An existing standalone home directly at `~/.codex-cli` keeps its files there.
The named homes are subdirectories.

Credential files contain reusable login secrets. Keep them private.
