"""Install and serve the pinned original BMO PNG frames."""
import hashlib
import os
import tempfile
from pathlib import Path
from urllib.request import urlopen

FOLDER = Path(__file__).with_name("faces")
UPSTREAM = "https://raw.githubusercontent.com/brenpoly/be-more-agent/5fb755809583c8338b1205075b2d465baa9b49ef/faces"
FRAMES = {
    "idle": ("e9a72fcb29dd9fb7c2bd752484e2e7ff7ebb3f7ec6e8da00ab8eb5110c187ad7",),
    "listening": (
        "161f63530f51fe256abf715f82c38831a4a8ab7fc8995290b74f5aa971b84975",
        "e94cc26b01febc98862eccbfc8b6ce2e445ed1275a6ce1a703a714fc4514e81d",
    ),
    "speaking": (
        "ed93d296e090129c338b94dc3fa400b892b16d1838f83deb67913a22e8400cf7",
        "17ffa4b8470de2ac6a22b57cd25e28aa0287f032026163136fef8458aca265fc",
        "df377320e2f40d276c839734b8a87836fa7a752bf23d74f83b556906e7da5c98",
    ),
    "thinking": (
        "10b2fbfb8a80febda4e829ee5a8bfa58d3ffa5890e0dc38fdbb00ec579892a98",
        "e1b2587f2a9a9b1c10f2780386850e20bf5618869a4d3d9e402e2dbbaaae7652",
        "6fbe75c5cb48b61dfc6fa5fedf902e6d7ffec9943708d529cf6e61def0dc1f3c",
        "052840df843a4ee2a7005b9c559bba9ae450deb993e456db01559cbdb7bf3bb1",
    ),
    "warmup": ("12f4fd054e817c246f94aaa64dad9e87f748b1caf6578914d635d283feb1416b",),
    "error": ("a229f0ad0ccd173fd98eb91a18cde34dc76d0edc1dff3654054cb8407e00c673",),
    "capturing": ("5e130672aaafe5a3929202dc5bc39dadf9be2febb1e054df9bf42df98bd7e8c0",),
}
MAX_BYTES = 65536


def matches(path, digest):
    return (path.is_file() and path.stat().st_size <= MAX_BYTES
            and hashlib.sha256(path.read_bytes()).hexdigest() == digest)


def face_manifest(folder=FOLDER):
    frames = {}
    for state, hashes in FRAMES.items():
        paths = [folder / f"{state}-{i}.png" for i in range(1, len(hashes) + 1)]
        frames[state] = [p.name for p, digest in zip(paths, hashes) if matches(p, digest)]
    return frames


def install(folder=FOLDER):
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        for state, hashes in FRAMES.items():
            for i, digest in enumerate(hashes, 1):
                target = folder / f"{state}-{i}.png"
                if matches(target, digest):
                    continue
                prefix = "listen" if state == "listening" else state
                url = f"{UPSTREAM}/{state}/{prefix}%20{i:02}.png"
                staged = Path(tmp) / target.name
                with urlopen(url, timeout=20) as response:
                    staged.write_bytes(response.read(MAX_BYTES + 1))
                if not matches(staged, digest):
                    raise ValueError(f"Original BMO frame checksum failed for {target.name}")
                os.replace(staged, target)
    print("Original BMO face pack ready.")


if __name__ == "__main__":
    install()
