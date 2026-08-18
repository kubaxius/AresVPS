from pathlib import Path

IMAGE_URL: str = (
    "https://cloud-images.ubuntu.com"
    "/releases/noble/release/ubuntu-24.04-server-cloudimg-amd64.img"
)
IMAGE_HASH_URL: str = (
    "https://cloud-images.ubuntu.com/releases/noble/release/SHA256SUMS"
)

PROJECT_PATH: Path = Path(__file__).resolve().parent.parent
IMAGE_DIR: Path = PROJECT_PATH / "vm"

IMAGE_PATH: Path = IMAGE_DIR / "ubuntu-24.04-server-cloudimg-amd64.img"
HASH_PATH: Path = IMAGE_DIR / "SHA256SUMS"
