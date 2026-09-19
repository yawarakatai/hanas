# Initial tools: Python
# Package source: github:NixOS/nixpkgs/nixos-unstable (pinned in flake.lock)
# Find package names: https://search.nixos.org/packages?channel=unstable

{
  systems = [ "x86_64-linux" ];

  packages = [
    "basedpyright"
    "curl" # Engine の疎通確認用
    "pipewire" # pw-play
    "python3"
    "ruff"
    "uv"
    "wl-clipboard" # wl-paste
  ];
}
