# ai_generated

"""Safely install and activate versioned static-site release artifacts.

Ansible installs this module once. A small, site-specific launcher supplies the
configuration mapping to :func:`main`; this module never discovers settings
from the environment, working directory, or the path used to invoke it.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import fcntl
import grp
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tarfile
import tempfile
from typing import NoReturn, TextIO, TypedDict, cast


SITE_ROOT_BASE = Path("/srv/www")
STORED_CHECKSUM = ".release-archive.sha256"
STORED_MANIFEST = ".release-manifest.json"

# These expressions validate values that later become filenames or directory
# names. Keeping them strict prevents user-controlled paths from escaping the
# site-specific release tree.
SITE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
GROUP_RE = re.compile(r"^[a-z_][a-z0-9_-]*[$]?$")
TAG_RE = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
RELEASE_ID_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-[0-9a-f]{12}$"
)
CHECKSUM_RE = re.compile(r"^([0-9a-f]{64}) [ *]([^/\r\n]+)\n?$")

CONFIG_KEYS = {
    "site_name",
    "site_root",
    "web_group",
    "manifest_schema_version",
    "release_retention",
    "archive_max_members",
    "archive_max_expanded_size",
    "required_entrypoints",
    "health_check_address",
    "health_check_port",
    "health_check_host",
    "health_check_timeout",
    "health_checks",
}


class ReleaseManifest(TypedDict):
    """The exact metadata stored beside and inside every release archive."""

    schema_version: int
    site: str
    tag: str
    commit: str
    release_id: str


class ReleaseError(Exception):
    """A safe, user-facing release operation failure."""


def fail(message: str) -> NoReturn:
    raise ReleaseError(message)


def _string(value: object, name: str) -> str:
    """Narrow an arbitrary configuration value to a safe string."""

    if not isinstance(value, str) or not value:
        fail(f"configuration value {name} must be a non-empty string")
    if "\x00" in value or "\r" in value or "\n" in value:
        fail(f"configuration value {name} contains unsafe characters")
    return value


def _integer(value: object, name: str, minimum: int) -> int:
    """Narrow a value to an integer, deliberately excluding booleans."""

    if type(value) is not int or value < minimum:
        fail(f"configuration value {name} must be an integer >= {minimum}")
    return value


def _relative_path(value: object, name: str) -> str:
    """Validate a normalized POSIX path that cannot leave its base path."""

    text = _string(value, name)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or str(path) != text:
        fail(f"configuration value {name} must be a normalized relative path")
    return text


@dataclass(frozen=True)
class HealthCheck:
    """One HTTP response that must succeed after switching ``current``."""

    path: str
    status: int
    location: str | None = None


@dataclass(frozen=True)
class SiteConfig:
    """Validated, immutable configuration for one website instance."""

    site_name: str
    site_root: Path
    web_group: str
    manifest_schema_version: int
    release_retention: int
    archive_max_members: int
    archive_max_expanded_size: int
    required_entrypoints: tuple[str, ...]
    health_check_address: str
    health_check_port: int
    health_check_host: str
    health_check_timeout: int
    health_checks: tuple[HealthCheck, ...]

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> SiteConfig:
        """Convert the launcher's untrusted runtime mapping into typed data.

        Although Ansible owns the launcher, validating at the privilege
        boundary keeps a malformed or manually edited launcher from widening
        the helper's filesystem access.
        """
        if set(values) != CONFIG_KEYS:
            missing = sorted(CONFIG_KEYS - set(values))
            extra = sorted(set(values) - CONFIG_KEYS)
            fail(f"configuration fields do not match schema; missing={missing}, extra={extra}")

        site_name = _string(values["site_name"], "site_name")
        if SITE_NAME_RE.fullmatch(site_name) is None:
            fail("configuration value site_name is not a safe identifier")

        root_text = _string(values["site_root"], "site_root")
        site_root = Path(root_text)
        if not site_root.is_absolute() or Path(os.path.normpath(root_text)) != site_root:
            fail("configuration value site_root must be a normalized absolute path")
        try:
            relative_root = site_root.relative_to(SITE_ROOT_BASE)
        except ValueError:
            fail(f"configuration value site_root must be beneath {SITE_ROOT_BASE}")
        if len(relative_root.parts) != 1 or relative_root.parts[0] in ("", ".", ".."):
            fail(f"configuration value site_root must be a direct child of {SITE_ROOT_BASE}")

        web_group = _string(values["web_group"], "web_group")
        if GROUP_RE.fullmatch(web_group) is None:
            fail("configuration value web_group is not a valid group name")

        raw_entrypoints = values["required_entrypoints"]
        if not isinstance(raw_entrypoints, Sequence) or isinstance(raw_entrypoints, str):
            fail("configuration value required_entrypoints must be a list")
        entrypoint_values = cast(Sequence[object], raw_entrypoints)
        entrypoints = tuple(
            _relative_path(value, f"required_entrypoints[{index}]")
            for index, value in enumerate(entrypoint_values)
        )
        if not entrypoints or len(set(entrypoints)) != len(entrypoints):
            fail("configuration value required_entrypoints must be non-empty and unique")

        raw_checks = values["health_checks"]
        if not isinstance(raw_checks, Sequence) or isinstance(raw_checks, str):
            fail("configuration value health_checks must be a list")
        check_values = cast(Sequence[object], raw_checks)
        checks: list[HealthCheck] = []
        for index, raw_check in enumerate(check_values):
            if not isinstance(raw_check, Mapping):
                fail(f"health_checks[{index}] must be an object")
            check_mapping = cast(Mapping[object, object], raw_check)
            if set(check_mapping) not in (
                {"path", "status"},
                {"path", "status", "location"},
            ):
                fail(f"health_checks[{index}] has invalid fields")
            path = _string(check_mapping["path"], f"health_checks[{index}].path")
            if not path.startswith("/") or path.startswith("//"):
                fail(f"health_checks[{index}].path must be an absolute HTTP path")
            status = _integer(
                check_mapping["status"], f"health_checks[{index}].status", 100
            )
            if status > 599:
                fail(f"health_checks[{index}].status must be <= 599")
            location_value = check_mapping.get("location")
            location = None
            if location_value is not None:
                location = _string(location_value, f"health_checks[{index}].location")
                if not location.startswith("/") or location.startswith("//"):
                    fail(f"health_checks[{index}].location must be an absolute path")
            checks.append(HealthCheck(path, status, location))
        if not checks:
            fail("configuration value health_checks must be non-empty")

        port = _integer(values["health_check_port"], "health_check_port", 1)
        if port > 65535:
            fail("configuration value health_check_port must be <= 65535")

        return cls(
            site_name=site_name,
            site_root=site_root,
            web_group=web_group,
            manifest_schema_version=_integer(
                values["manifest_schema_version"], "manifest_schema_version", 1
            ),
            release_retention=_integer(values["release_retention"], "release_retention", 0),
            archive_max_members=_integer(
                values["archive_max_members"], "archive_max_members", 1
            ),
            archive_max_expanded_size=_integer(
                values["archive_max_expanded_size"], "archive_max_expanded_size", 1
            ),
            required_entrypoints=entrypoints,
            health_check_address=_string(
                values["health_check_address"], "health_check_address"
            ),
            health_check_port=port,
            health_check_host=_string(values["health_check_host"], "health_check_host"),
            health_check_timeout=_integer(
                values["health_check_timeout"], "health_check_timeout", 1
            ),
            health_checks=tuple(checks),
        )


@dataclass(frozen=True)
class CommandArguments:
    """Typed representation of the selected command-line subcommand."""

    command: str
    archive: str | None = None
    checksum: str | None = None
    manifest: str | None = None
    release_id: str | None = None


class ReleaseManager:
    """Perform release operations within one validated site root."""

    def __init__(self, config: SiteConfig):
        self.config = config
        self.incoming_dir = config.site_root / "incoming"
        self.releases_dir = config.site_root / "releases"
        self.current_link = config.site_root / "current"
        self.lock_file = config.site_root / ".release.lock"

    def validate_layout(self) -> None:
        """Reject missing directories and symlinks in the trusted layout."""

        # Ansible creates these directories. Refusing symlinks here prevents a
        # local filesystem change from redirecting root-owned operations.
        for path in (SITE_ROOT_BASE, self.config.site_root, self.incoming_dir, self.releases_dir):
            try:
                info = path.lstat()
            except OSError as error:
                fail(f"required deployment path is unavailable: {path}: {error}")
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                fail(f"required deployment path is not a real directory: {path}")

    @staticmethod
    def validate_release_id(release_id: str) -> str:
        if RELEASE_ID_RE.fullmatch(release_id) is None:
            fail(f"invalid release ID: {release_id!r}")
        return release_id

    def snapshot_input(self, path_text: str, destination: Path) -> tuple[Path, Path]:
        """Copy one upload into private staging without following symlinks."""

        path = Path(path_text)
        try:
            resolved_parent = path.parent.resolve(strict=True)
            expected = self.incoming_dir.resolve(strict=True)
        except OSError as error:
            fail(f"cannot inspect input {path}: {error}")
        if resolved_parent != expected:
            fail(f"input must be directly inside {self.incoming_dir}: {path}")
        # Work only on a snapshot. The deploy user may modify incoming files,
        # so validation must not race with later extraction or hashing.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = -1
        try:
            descriptor = os.open(path, flags)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                fail(f"input must be a regular file: {path}")
            with os.fdopen(descriptor, "rb") as source:
                descriptor = -1
                with destination.open("xb") as output:
                    shutil.copyfileobj(source, output)
        except OSError as error:
            fail(f"cannot snapshot input {path}: {error}")
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        return path, destination

    def read_manifest(self, path: Path) -> tuple[ReleaseManifest, bytes]:
        """Validate both manifest field types and their relationships."""

        try:
            raw = path.read_bytes()
            decoded: object = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            fail(f"invalid manifest {path.name}: {error}")
        if not isinstance(decoded, dict):
            fail("manifest must be a JSON object")
        manifest = cast(dict[object, object], decoded)
        expected_keys = {"schema_version", "site", "tag", "commit", "release_id"}
        if set(manifest) != expected_keys:
            fail("manifest fields do not match the required schema")
        schema_version = manifest["schema_version"]
        site = manifest["site"]
        tag = manifest["tag"]
        commit = manifest["commit"]
        release_id = manifest["release_id"]
        if type(schema_version) is not int:
            fail("manifest schema_version must be an integer")
        if schema_version != self.config.manifest_schema_version:
            fail("manifest schema version does not match this server")
        if not isinstance(site, str) or site != self.config.site_name:
            fail("manifest site does not match this server")
        if not isinstance(tag, str) or TAG_RE.fullmatch(tag) is None:
            fail("manifest tag is not a valid vMAJOR.MINOR.PATCH tag")
        if not isinstance(commit, str) or COMMIT_RE.fullmatch(commit) is None:
            fail("manifest commit is not a lowercase 40-character Git SHA")
        if not isinstance(release_id, str) or release_id != f"{tag}-{commit[:12]}":
            fail("manifest release_id does not match its tag and commit")
        self.validate_release_id(release_id)
        return ReleaseManifest(
            schema_version=schema_version,
            site=site,
            tag=tag,
            commit=commit,
            release_id=release_id,
        ), raw

    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as error:
            fail(f"cannot read archive {path.name}: {error}")
        return digest.hexdigest()

    @staticmethod
    def read_checksum(path: Path, archive_name: str) -> str:
        try:
            contents = path.read_text(encoding="ascii")
        except (OSError, UnicodeDecodeError) as error:
            fail(f"invalid checksum file {path.name}: {error}")
        match = CHECKSUM_RE.fullmatch(contents)
        if match is None or match.group(2) != archive_name:
            fail("checksum file must name the exact uploaded archive")
        return match.group(1)

    @staticmethod
    def normalized_member_name(member: tarfile.TarInfo) -> PurePosixPath | None:
        name = member.name
        if not name or name.startswith("/"):
            fail(f"unsafe archive path: {name!r}")
        parts = PurePosixPath(name).parts
        if ".." in parts:
            fail(f"unsafe archive path: {name!r}")
        clean_parts = tuple(part for part in parts if part not in ("", "."))
        if not clean_parts:
            if member.isdir():
                return None
            fail("archive payload root must be a directory")
        return PurePosixPath(*clean_parts)

    def inspect_archive(
        self, archive: tarfile.TarFile
    ) -> list[tuple[tarfile.TarInfo, PurePosixPath]]:
        """Preflight every member before writing any payload file."""

        members = archive.getmembers()
        if len(members) > self.config.archive_max_members:
            fail(f"archive contains more than {self.config.archive_max_members} members")
        expanded_size = 0
        inspected: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
        seen: set[PurePosixPath] = set()
        file_paths: set[PurePosixPath] = set()
        for member in members:
            if not (member.isfile() or member.isdir()):
                fail(f"archive contains unsupported member: {member.name!r}")
            normalized = self.normalized_member_name(member)
            if normalized is None:
                continue
            if normalized in seen:
                fail(f"archive contains duplicate path: {normalized}")
            if any(parent in file_paths for parent in normalized.parents):
                fail(f"archive places content beneath a file: {normalized}")
            if member.isfile():
                if any(path != normalized and normalized in path.parents for path in seen):
                    fail(f"archive file conflicts with a directory: {normalized}")
                if member.size < 0:
                    fail(f"archive member has an invalid size: {normalized}")
                expanded_size += member.size
                if expanded_size > self.config.archive_max_expanded_size:
                    fail(
                        "archive expands beyond "
                        f"{self.config.archive_max_expanded_size} bytes"
                    )
                file_paths.add(normalized)
            seen.add(normalized)
            inspected.append((member, normalized))
        return inspected

    def extract_archive(self, archive_path: Path, destination: Path) -> None:
        """Extract only the regular files and directories approved above."""

        # Avoid TarFile.extract(): writing each approved member ourselves
        # makes the destination path and accepted member types explicit.
        try:
            with tarfile.open(archive_path, mode="r:gz") as archive:
                for member, normalized in self.inspect_archive(archive):
                    target = destination.joinpath(*normalized.parts)
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        fail(f"cannot read archive member: {member.name!r}")
                    with source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
        except (OSError, tarfile.TarError) as error:
            fail(f"cannot extract archive {archive_path.name}: {error}")

    def validate_entrypoints(self, release_dir: Path) -> None:
        for entrypoint in self.config.required_entrypoints:
            path = release_dir.joinpath(*PurePosixPath(entrypoint).parts)
            if not path.is_file() or path.is_symlink():
                fail(f"release is missing required entrypoint: {entrypoint}")

    def normalize_release(self, release_dir: Path) -> None:
        """Make completed content root-owned and read-only to deploy users."""

        try:
            group_id = grp.getgrnam(self.config.web_group).gr_gid
            for root, directory_names, file_names in os.walk(release_dir):
                root_path = Path(root)
                os.chown(root_path, 0, group_id, follow_symlinks=False)
                root_path.chmod(0o755)
                for name in directory_names:
                    path = root_path / name
                    os.chown(path, 0, group_id, follow_symlinks=False)
                    path.chmod(0o755)
                for name in file_names:
                    path = root_path / name
                    os.chown(path, 0, group_id, follow_symlinks=False)
                    path.chmod(0o644)
            release_dir.chmod(0o750)
        except (KeyError, OSError) as error:
            fail(f"cannot normalize release ownership and permissions: {error}")

    def install(self, archive_text: str, checksum_text: str, manifest_text: str) -> None:
        """Validate and atomically publish an inactive release directory."""

        # Staging under releases guarantees the final rename stays on one
        # filesystem. Installation intentionally never changes ``current``.
        temporary = Path(tempfile.mkdtemp(prefix=".install-", dir=self.releases_dir))
        try:
            archive_path, archive_snapshot = self.snapshot_input(
                archive_text, temporary / "archive.upload"
            )
            checksum_path, checksum_snapshot = self.snapshot_input(
                checksum_text, temporary / "checksum.upload"
            )
            manifest_path, manifest_snapshot = self.snapshot_input(
                manifest_text, temporary / "manifest.upload"
            )
            manifest, manifest_bytes = self.read_manifest(manifest_snapshot)
            release_id = str(manifest["release_id"])
            expected_archive = f"{self.config.site_name}-{release_id}.tar.gz"
            expected_manifest = f"{self.config.site_name}-{release_id}.manifest.json"
            if archive_path.name != expected_archive:
                fail(f"archive must be named {expected_archive}")
            if checksum_path.name != f"{expected_archive}.sha256":
                fail(f"checksum must be named {expected_archive}.sha256")
            if manifest_path.name != expected_manifest:
                fail(f"manifest must be named {expected_manifest}")
            expected_digest = self.read_checksum(checksum_snapshot, expected_archive)
            actual_digest = self.sha256_file(archive_snapshot)
            if actual_digest != expected_digest:
                fail("archive checksum does not match")

            final_dir = self.releases_dir / release_id
            if final_dir.exists() or final_dir.is_symlink():
                # A byte-identical retry is safe (for example, after a CI
                # timeout). Reusing an ID for different bytes is forbidden.
                if not final_dir.is_dir() or final_dir.is_symlink():
                    fail(f"release path is not a directory: {release_id}")
                try:
                    stored_manifest = (final_dir / STORED_MANIFEST).read_bytes()
                    stored_checksum = (final_dir / STORED_CHECKSUM).read_text(
                        encoding="ascii"
                    ).strip()
                except OSError as error:
                    fail(f"cannot verify existing release {release_id}: {error}")
                if stored_manifest == manifest_bytes and stored_checksum == actual_digest:
                    return
                fail(f"release {release_id} already exists with different content")

            payload = temporary / "payload"
            payload.mkdir()
            self.extract_archive(archive_snapshot, payload)
            internal_manifest = payload / STORED_MANIFEST
            try:
                archived_manifest = internal_manifest.read_bytes()
            except OSError as error:
                fail(f"archive does not contain {STORED_MANIFEST}: {error}")
            if archived_manifest != manifest_bytes:
                fail("manifest inside archive differs from uploaded manifest")
            self.validate_entrypoints(payload)
            (payload / STORED_CHECKSUM).write_text(f"{actual_digest}\n", encoding="ascii")
            self.normalize_release(payload)
            try:
                payload.rename(final_dir)
            except FileExistsError:
                fail(f"release {release_id} appeared during installation")
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def release_directory(self, release_id: str) -> Path:
        self.validate_release_id(release_id)
        path = self.releases_dir / release_id
        if not path.is_dir() or path.is_symlink():
            fail(f"release is not installed: {release_id}")
        return path

    def current_release(self, required: bool = False) -> str | None:
        """Return the active ID after validating the complete symlink shape."""

        if not self.current_link.is_symlink():
            if self.current_link.exists():
                fail(f"current path is not a symbolic link: {self.current_link}")
            if required:
                fail("no release is currently active")
            return None
        try:
            target = Path(os.readlink(self.current_link))
        except OSError as error:
            fail(f"cannot read current release: {error}")
        if target.is_absolute() or len(target.parts) != 2 or target.parts[0] != "releases":
            fail("current symlink does not point directly inside releases")
        release_id = self.validate_release_id(target.parts[1])
        self.release_directory(release_id)
        return release_id

    def replace_current(self, release_id: str) -> None:
        """Atomically point ``current`` at an already validated release."""

        # The relative target keeps the deployment tree relocatable while the
        # exact two-component shape is enforced by current_release().
        temporary = self.config.site_root / f".current-{os.getpid()}"
        try:
            temporary.unlink(missing_ok=True)
            temporary.symlink_to(Path("releases") / release_id)
            os.replace(temporary, self.current_link)
        except OSError as error:
            fail(f"cannot switch current release: {error}")
        finally:
            temporary.unlink(missing_ok=True)

    def health_check(self) -> None:
        """Verify that Nginx serves the newly selected release as expected."""

        for check in self.config.health_checks:
            connection = http.client.HTTPConnection(
                self.config.health_check_address,
                self.config.health_check_port,
                timeout=self.config.health_check_timeout,
            )
            try:
                connection.putrequest("GET", check.path, skip_host=True)
                connection.putheader("Host", self.config.health_check_host)
                connection.putheader("Connection", "close")
                connection.endheaders()
                response = connection.getresponse()
                response.read()
            except (OSError, http.client.HTTPException) as error:
                fail(f"health check for {check.path} failed: {error}")
            finally:
                connection.close()
            if response.status != check.status:
                fail(
                    f"health check for {check.path} returned {response.status}, "
                    f"expected {check.status}"
                )
            if check.location is not None and response.getheader("Location") != check.location:
                fail(f"health check for {check.path} returned an unexpected Location header")

    def installed_releases(self) -> list[Path]:
        try:
            paths = [
                path
                for path in self.releases_dir.iterdir()
                if path.is_dir()
                and not path.is_symlink()
                and RELEASE_ID_RE.fullmatch(path.name)
            ]
            return sorted(paths, key=lambda path: (-path.stat().st_mtime_ns, path.name))
        except OSError as error:
            fail(f"cannot list releases: {error}")

    def prune_releases(self, active: str, previous: str | None) -> None:
        """Apply retention without deleting active or rollback-safe content."""

        inactive = [path for path in self.installed_releases() if path.name != active]
        retained: set[str] = set()
        if previous is not None and any(path.name == previous for path in inactive):
            retained.add(previous)
        for path in inactive:
            if len(retained) >= self.config.release_retention:
                break
            retained.add(path.name)
        for path in inactive:
            if path.name not in retained:
                try:
                    shutil.rmtree(path)
                except OSError as error:
                    fail(f"cannot prune release {path.name}: {error}")

    def activate(self, release_id: str) -> None:
        """Switch releases, restoring the old target if health checks fail."""

        self.release_directory(release_id)
        previous = self.current_release()
        if previous == release_id:
            self.health_check()
            self.prune_releases(release_id, previous)
            return
        self.replace_current(release_id)
        try:
            self.health_check()
        except ReleaseError:
            if previous is None:
                try:
                    self.current_link.unlink(missing_ok=True)
                except OSError as error:
                    fail(f"health check failed and current could not be removed: {error}")
            else:
                self.replace_current(previous)
            raise
        self.prune_releases(release_id, previous)

    def print_current(self, output: TextIO) -> None:
        print(self.current_release(required=True), file=output)

    def list_releases(self, output: TextIO) -> None:
        for path in self.installed_releases():
            print(path.name, file=output)

    def run(self, arguments: CommandArguments, output: TextIO) -> None:
        """Serialize and dispatch one command for this website."""

        self.validate_layout()
        try:
            lock = self.lock_file.open("a", encoding="ascii")
        except OSError as error:
            fail(f"cannot open release lock: {error}")
        with lock:
            # flock is scoped to this site's lock file. Two sites can deploy
            # independently, while concurrent commands for one site serialize.
            fcntl.flock(lock, fcntl.LOCK_EX)
            if arguments.command == "install":
                if (
                    arguments.archive is None
                    or arguments.checksum is None
                    or arguments.manifest is None
                ):
                    fail("install arguments are incomplete")
                self.install(arguments.archive, arguments.checksum, arguments.manifest)
            elif arguments.command in ("activate", "rollback"):
                if arguments.release_id is None:
                    fail(f"{arguments.command} requires a release ID")
                self.activate(arguments.release_id)
            elif arguments.command == "current":
                self.print_current(output)
            elif arguments.command == "list":
                self.list_releases(output)


def build_parser(site_name: str) -> argparse.ArgumentParser:
    """Build the public command-line interface shared by every launcher."""

    command_parser = argparse.ArgumentParser(
        description=f"Install and activate releases for {site_name}"
    )
    subparsers = command_parser.add_subparsers(dest="command", required=True)
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("--archive", required=True)
    install_parser.add_argument("--checksum", required=True)
    install_parser.add_argument("--manifest", required=True)
    for command in ("activate", "rollback"):
        action_parser = subparsers.add_parser(command)
        action_parser.add_argument("release_id")
    subparsers.add_parser("current")
    subparsers.add_parser("list")
    return command_parser


def parse_arguments(site_name: str, argv: Sequence[str] | None) -> CommandArguments:
    """Narrow argparse's dynamic namespace to a statically typed value."""

    namespace = build_parser(site_name).parse_args(argv)
    command_value: object = getattr(namespace, "command", None)
    if not isinstance(command_value, str):
        fail("no command was selected")

    def optional_string(name: str) -> str | None:
        value: object = getattr(namespace, name, None)
        if value is None or isinstance(value, str):
            return value
        fail(f"command-line argument {name} must be a string")

    return CommandArguments(
        command=command_value,
        archive=optional_string("archive"),
        checksum=optional_string("checksum"),
        manifest=optional_string("manifest"),
        release_id=optional_string("release_id"),
    )


def main(site_config: Mapping[str, object], argv: Sequence[str] | None = None) -> int:
    """Validate launcher configuration, parse the CLI, and run one command."""

    try:
        config = SiteConfig.from_mapping(site_config)
        arguments = parse_arguments(config.site_name, argv)
        ReleaseManager(config).run(arguments, sys.stdout)
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
