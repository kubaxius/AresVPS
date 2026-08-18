# tools for downloading and checking system image

from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlretrieve

import typer
import pantheon_systems_cli.console as c
from pantheon_systems_cli.config import (
    HASH_PATH,
    IMAGE_DIR,
    IMAGE_HASH_URL,
    IMAGE_PATH,
    IMAGE_URL,
)


def _download(url: str, target_path: Path) -> None:
    temp_path: Path = target_path.with_suffix(target_path.suffix + ".tmp")
    try:
        urlretrieve(url, temp_path)
        temp_path.replace(target_path)
    except (URLError, OSError):
        temp_path.unlink(missing_ok=True)
        raise


def _get_image_checksum(file_path: Path = HASH_PATH) -> str | None:
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


def _download_latest_checksum() -> Path:
    new_hash_path = HASH_PATH.with_name(f"{HASH_PATH.stem}_new{HASH_PATH.suffix}")
    _download(IMAGE_HASH_URL, new_hash_path)
    return new_hash_path


def _is_image_up_to_date(latest_hash_path: Path) -> bool:
    latest_checksum = _get_image_checksum(latest_hash_path)

    if latest_checksum is None:
        raise ValueError(
            f"No checksum found for {IMAGE_PATH.name} in {latest_hash_path}"
        )

    return (
        _get_image_checksum(HASH_PATH) == latest_checksum and _is_image_checksum_valid()
    )


def _is_image_checksum_valid() -> bool:
    if not IMAGE_PATH.is_file() or not HASH_PATH.is_file():
        return False

    expected_checksum: str | None = _get_image_checksum()

    if expected_checksum is None:
        return False

    image_hash = sha256()
    with IMAGE_PATH.open("rb") as image_file:
        while chunk := image_file.read(1024 * 1024):  # 1 MiB chunks
            image_hash.update(chunk)

    return compare_digest(image_hash.hexdigest(), expected_checksum)


def _download_image() -> None:
    _download(IMAGE_URL, IMAGE_PATH)


app = typer.Typer(help="Manage the VM system image.", no_args_is_help=True)


# TODO: This currently overrides the existing file and only then checks if
# new one is correct. Should be more robust.
@app.command()
def update() -> None:
    """Download the latest image when necessary."""

    latest_hash_path: Path | None = None

    try:
        latest_hash_path = _download_latest_checksum()

        if _is_image_up_to_date(latest_hash_path):
            c.success("Image already up to date.")
            return

        latest_hash_path.replace(HASH_PATH)
        _download_image()

        if not _is_image_checksum_valid():
            IMAGE_PATH.unlink(missing_ok=True)
            c.error("Checksum does not match the downloaded image. Please try again.")
            raise typer.Exit(1)

        c.success("Image successfully updated!")

    except URLError as error:
        c.error(f"Network error: {error.reason}. Please retry.")
        raise typer.Exit(1)
    except OSError as error:
        c.error(f"File error: {error}")
        raise typer.Exit(1)
    except ValueError as error:
        c.error(f"Invalid checksum file: {error}")
        raise typer.Exit(1)
    finally:
        if latest_hash_path is not None:
            latest_hash_path.unlink(missing_ok=True)


@app.command()
def download() -> None:
    """Download the latest image when necessary."""
    update()


@app.command()
def flush() -> None:
    """Remove all files in the image downloading directory."""
    try:
        for file in IMAGE_DIR.iterdir():
            file.unlink()
            c.info(f"{file.name} successfully removed.")
    except OSError as error:
        c.error(f"Error: {error}")
        raise typer.Exit(1)


# TODO: lock() command
