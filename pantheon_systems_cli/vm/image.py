# tools for downloading and checking system image

from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlretrieve

from pantheon_systems_cli.config import HASH_PATH, IMAGE_HASH_URL, IMAGE_PATH


def download(url: str, target_path: Path) -> None:
    temp_path: Path = target_path.with_suffix(target_path.suffix + ".tmp")
    try:
        urlretrieve(url, temp_path)
        temp_path.replace(target_path)
    except (URLError, OSError):
        temp_path.unlink(missing_ok=True)
        raise


def get_image_checksum(file_path: Path = HASH_PATH) -> str | None:
    if not file_path.is_file():
        return None

    expected_checksum: str | None = None
    with file_path.open(encoding="utf-8") as hash_file:
        for line in hash_file:
            checksum, separator, filename = line.strip().partition(" ")
            if separator and filename.lstrip(" *") == IMAGE_PATH.name:
                expected_checksum = checksum
                break
    return expected_checksum


def download_latest_checksum() -> Path:
    new_hash_path = HASH_PATH.with_name(f"{HASH_PATH.stem}_new{HASH_PATH.suffix}")
    download(IMAGE_HASH_URL, new_hash_path)
    return new_hash_path


def is_image_up_to_date(latest_hash_path: Path) -> bool:
    latest_checksum = get_image_checksum(latest_hash_path)

    if latest_checksum is None:
        raise ValueError(
            f"No checksum found for {IMAGE_PATH.name} in {latest_hash_path}"
        )

    return (
        get_image_checksum(HASH_PATH) == latest_checksum and is_image_checksum_valid()
    )


def is_image_checksum_valid() -> bool:
    if not IMAGE_PATH.is_file() or not HASH_PATH.is_file():
        return False

    expected_checksum: str | None = get_image_checksum()

    if expected_checksum is None:
        return False

    image_hash = sha256()
    with IMAGE_PATH.open("rb") as image_file:
        while chunk := image_file.read(1024 * 1024):  # 1 MiB chunks
            image_hash.update(chunk)

    return compare_digest(image_hash.hexdigest(), expected_checksum)
