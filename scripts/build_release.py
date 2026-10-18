"""Build a deterministic manual-install archive from committed runtime files."""

import hashlib
import subprocess
import zipfile

from validate_package import ROOT, validate


def build():
    validate()
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "custom_components/family_network"], cwd=ROOT
        )
        .decode()
        .split("\0")
    )
    paths = sorted(path for path in paths if path)
    if not paths:
        raise ValueError("Commit the package before building a release")
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    archive = output / "simplifi.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name in paths:
            source = ROOT / name
            if source.is_symlink():
                raise ValueError("Runtime symlinks are not supported")
            committed = subprocess.check_output(["git", "show", f"HEAD:{name}"], cwd=ROOT)
            if source.read_bytes() != committed:
                raise ValueError(f"Uncommitted runtime changes: {name}")
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, committed)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  simplifi.zip\n")
    print(f"Built {archive.name}: {len(paths)} files, SHA256 {digest}")


if __name__ == "__main__":
    build()
