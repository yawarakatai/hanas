{
  autoPatchelfHook,
  cacert,
  fetchurl,
  lib,
  makeWrapper,
  p7zip,
  stdenvNoCC,
}:

stdenvNoCC.mkDerivation (finalAttrs: {
  pname = "aivisspeech-engine-bin";
  version = "1.2.0";

  src = fetchurl {
    url = "https://github.com/Aivis-Project/AivisSpeech-Engine/releases/download/${finalAttrs.version}/AivisSpeech-Engine-Linux-x64-${finalAttrs.version}.7z.001";
    hash = "sha256-pLHMeQ6aFSLYgOBj14jqLDPfkJ6I52TYrloX41l7FbU=";
  };

  nativeBuildInputs = [
    autoPatchelfHook
    makeWrapper
    p7zip
  ];

  dontUnpack = true;

  installPhase = ''
    runHook preInstall

    7z x "$src"
    mkdir -p "$out/lib" "$out/bin"
    cp -r Linux-x64 "$out/lib/aivisspeech-engine"
    chmod +x "$out/lib/aivisspeech-engine/run"
    makeWrapper "$out/lib/aivisspeech-engine/run" "$out/bin/aivisspeech-engine" \
      --set-default SSL_CERT_FILE "${cacert}/etc/ssl/certs/ca-bundle.crt"

    runHook postInstall
  '';

  # CPU inference does not use these optional GPU libraries.
  autoPatchelfIgnoreMissingDeps = [
    "libcuda.so.1"
    "libcudart.so.12"
    "libcudnn.so.9"
    "libcublas.so.12"
    "libcublasLt.so.12"
    "libcufft.so.11"
    "libcurand.so.10"
    "libnvJitLink.so.12"
    "libnvinfer.so.10"
    "libnvonnxparser.so.10"
    "libtcl9.0.so"
    "libtcl9tk9.0.so"
  ];

  meta = {
    description = "AivisSpeech Engine binary distribution";
    homepage = "https://github.com/Aivis-Project/AivisSpeech-Engine";
    license = lib.licenses.lgpl3Only;
    platforms = [ "x86_64-linux" ];
    mainProgram = "aivisspeech-engine";
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
})
