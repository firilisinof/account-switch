# account-switch

A macOS CLI for switching ChatGPT accounts in Codex CLI and the unified ChatGPT/Codex desktop app. It replaces `auth.json` and keeps your configuration, MCP connections, plugins, and local conversation history in the same Codex home.

## Requirements

Python 3.11 or newer and Codex CLI on `PATH`. The script uses only the Python standard library and needs no installation.

Sign in with `codex login` before saving your first profile. File-based authentication is required. The tool rejects `keyring`, `auto`, and `ephemeral` storage settings and leaves `config.toml` unchanged.

## Usage

Run from this directory:

```sh
./account-switch save personal
./account-switch login work
./account-switch list
./account-switch use work
./account-switch use personal
```

`save` names your current login. `login` saves another account through browser sign-in without changing the active login. Choose the intended account in the browser. Use `login NAME --device-auth` for device sign-in if your account allows it.

Before running `use`, finish desktop tasks and close Codex CLI sessions and standalone app servers. Run the command in a normal terminal. It refuses to switch while a CLI or server is running. If the desktop app is open, it quits and reopens it. Complete any quit dialog. A failed quit leaves credentials unchanged.

To rename, remove, or renew a profile:

```sh
./account-switch rename work second
./account-switch remove second
./account-switch login second
```

`remove` deletes an inactive saved login without signing out or deleting history. `login` also renews an existing profile and checks that the account matches. Switch away before renewing the active profile. If you sign in again outside this tool, `save NAME` updates the matching profile.

## Storage and limits

Profiles live in `~/.codex/account-switch/NAME.json`. The directory uses permissions `0700` and credential files use `0600`. These files contain reusable login secrets. Do not commit or share them.

Before switching, the tool saves the current account's latest credentials. It refuses to overwrite an unsaved login. Credential replacement is atomic, and only one switcher command can run at a time. Do not start Codex or another login tool during a switch.

Use `CODEX_HOME` or `--home PATH` to select another Codex home. The desktop app must use the same home. Automatic restart supports only `~/.codex` and `ChatGPT.app` or `Codex.app` in `/Applications` or `~/Applications`, with bundle ID `com.openai.codex`.

Cloud chats, subscriptions, permissions, and workspaces stay with their accounts. Expired or revoked logins require `login NAME` again. The tool checks credential structure and identity locally, without verifying tokens over the network.

Desktop switching depends on the app using Codex's file credentials and has not been verified with two real accounts.
