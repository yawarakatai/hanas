{
  lib,
  libnotify,
  makeWrapper,
  pipewire,
  python3Packages,
  wl-clipboard,
}:

python3Packages.buildPythonApplication {
  pname = "hanas";
  version = "0.1.0";
  pyproject = true;

  src = lib.cleanSourceWith {
    src = ../.;
    filter = path: type:
      let name = baseNameOf path;
      in
      lib.cleanSourceFilter path type
      && !(builtins.elem name [
        ".direnv"
        ".ruff_cache"
        ".venv"
        "__pycache__"
        "hanas.egg-info"
      ])
      && !(lib.hasSuffix ".pyc" name);
  };

  build-system = [ python3Packages.setuptools ];
  nativeBuildInputs = [ makeWrapper ];

  postInstall = ''
    mkdir -p "$out/share/systemd/user" "$out/share/doc/hanas"
    substitute ${../examples/hanas.service.in} "$out/share/systemd/user/hanas.service" \
      --replace-fail '@hanas@' "$out/bin/hanas"
    cp ${../examples/niri.kdl} ${../config.example.toml} "$out/share/doc/hanas/"
  '';

  postFixup = ''
    wrapProgram "$out/bin/hanas" \
      --prefix PATH : ${lib.makeBinPath [ libnotify pipewire wl-clipboard ]}
  '';

  doCheck = true;
  checkPhase = ''
    runHook preCheck
    PYTHONPATH="$PWD/src" python -m unittest discover -s tests -v
    runHook postCheck
  '';

  meta = {
    description = "Desktop text-to-speech client for AivisSpeech and VOICEVOX";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "hanas";
  };
}
