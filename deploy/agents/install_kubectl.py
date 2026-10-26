"""Install the pinned upstream release, verifying its published checksum."""

import hashlib
import platform
import tarfile
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

architecture = {"aarch64": "arm64", "x86_64": "x86_64"}[platform.machine()]
name = f"kubectl-ai_Linux_{architecture}.tar.gz"
base = "https://github.com/GoogleCloudPlatform/kubectl-ai/releases/download/v0.0.31/"
with urlopen(base + "kubectl-ai_0.0.31_checksums.txt", timeout=60) as response:
    checksums = dict(
        line.split()[::-1] for line in response.read().decode().splitlines()
    )
with urlopen(base + name, timeout=60) as response:
    archive = response.read()
if hashlib.sha256(archive).hexdigest() != checksums[name]:
    raise ValueError("kubectl-ai release checksum mismatch")
with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as package:
    member = next(
        item
        for item in package.getmembers()
        if Path(item.name).name == "kubectl-ai" and item.isfile()
    )
    binary = package.extractfile(member)
    assert binary is not None
    target = Path("/usr/local/bin/kubectl-ai")
    target.write_bytes(binary.read())
    target.chmod(0o755)
