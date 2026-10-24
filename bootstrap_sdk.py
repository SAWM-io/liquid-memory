"""Download the public SDK with a pinned digest; never execute it here."""
from pathlib import Path
import hashlib
import os
import urllib.request

URL = "https://basira.sawm.io/static/sdk/basira_client.py"
SHA256 = "f7ce351e894fb9d8e42a63f2abff297758cf2927452e84ed97e31a00fbf109f7"


def install(data, destination):
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError("Public SDK changed: check the new release before updating the pinned digest.")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".download")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination)
    return destination


def main():
    request = urllib.request.Request(URL, headers={"User-Agent": "sawm-liquid-memory-example/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.geturl() != URL:
            raise ValueError("Unexpected SDK redirect; verify the distribution URL.")
        data = response.read(1_000_001)
    print(install(data, Path(__file__).parent / "vendor" / "basira_client.py"))


if __name__ == "__main__":
    main()
