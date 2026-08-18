# tools for downloading and checking system image

from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlretrieve

from pantheon_systems_cli.config import HASH_PATH, IMAGE_HASH_URL, IMAGE_PATH, IMAGE_URL


def download(url: str, target_path: Path) -> bool:
    temp_path: Path = target_path.with_suffix(target_path.suffix + ".tmp")
    try:
        urlretrieve(url, temp_path)
        temp_path.replace(target_path)
        return True
    except (HTTPError, URLError, OSError) as error:
        temp_path.unlink(missing_ok=True)
        print(f"Download failed: {error}")
        return False


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


def is_image_up_to_date() -> bool:
    new_hash_path: Path = HASH_PATH.with_name(f"{HASH_PATH.stem}_new{HASH_PATH.suffix}")

    if not download(IMAGE_HASH_URL, new_hash_path):
        return False

    new_hash: str | None = get_image_checksum(new_hash_path)
    if new_hash == None:
        print("Hash file or url incorrect!")
        new_hash_path.unlink(missing_ok=True)
        return True

    if (
        HASH_PATH.is_file()
        and get_image_checksum(HASH_PATH) == new_hash
        and is_image_checksum_valid()
    ):
        new_hash_path.unlink(missing_ok=True)
        return True

    new_hash_path.replace(HASH_PATH)
    return False


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


def update_or_download_image():
    if is_image_up_to_date():
        print("Image file is up to date.")
        return False
    download(IMAGE_URL, IMAGE_PATH)
    if not is_image_checksum_valid():
        print("Downloaded image is corrupted! Try again.")
        return False
    print("Image updated.")
    return True
