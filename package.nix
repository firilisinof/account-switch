{ lib, python3Packages }:

python3Packages.buildPythonApplication {
  pname = "codex-login";
  version = (builtins.fromTOML (builtins.readFile ./pyproject.toml)).project.version;
  pyproject = true;

  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      ./pyproject.toml
      ./README.md
      ./src/codex_login.py
    ];
  };

  build-system = [ python3Packages.hatchling ];
  pythonImportsCheck = [ "codex_login" ];

  meta = {
    description = "Manage Codex logins on macOS";
    mainProgram = "codex-login";
    platforms = lib.platforms.darwin;
  };
}
