# ai_generated

"""Health-gated coordinator for static-site releases installed by sysupdate."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import fcntl
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from typing import NoReturn, TextIO, cast


SITE_ROOT_BASE = Path("/srv/www")
RELEASE_ID_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-[0-9a-f]{12}$"
)
SITE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
CONFIG_KEYS = {
    "site_name",
    "site_root",
    "definitions_path",
    "required_entrypoints",
    "health_check_address",
    "health_check_port",
    "staging_health_check_port",
    "health_check_host",
    "health_check_timeout",
    "health_checks",
}


class ReleaseError(Exception):
    """A release operation failed without exposing an implementation traceback."""


def fail(message: str) -> NoReturn:
    raise ReleaseError(message)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"configuration value {name} must be a non-empty string")
    if any(character in value for character in ("\x00", "\r", "\n")):
        fail(f"configuration value {name} contains unsafe characters")
    return value


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        fail(f"configuration value {name} must be an integer from {minimum} to {maximum}")
    return value


def _absolute_path(value: object, name: str) -> Path:
    text = _string(value, name)
    path = Path(text)
    if not path.is_absolute() or Path(os.path.normpath(text)) != path:
        fail(f"configuration value {name} must be a normalized absolute path")
    return path


def _relative_path(value: object, name: str) -> str:
    text = _string(value, name)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or str(path) != text or text == ".":
        fail(f"configuration value {name} must be a normalized relative path")
    return text


@dataclass(frozen=True)
class HealthCheck:
    path: str
    status: int
    location: str | None = None


@dataclass(frozen=True)
class SiteConfig:
    site_name: str
    site_root: Path
    definitions_path: Path
    required_entrypoints: tuple[str, ...]
    health_check_address: str
    health_check_port: int
    staging_health_check_port: int
    health_check_host: str
    health_check_timeout: int
    health_checks: tuple[HealthCheck, ...]

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> SiteConfig:
        if set(values) != CONFIG_KEYS:
            missing = sorted(CONFIG_KEYS - set(values))
            extra = sorted(set(values) - CONFIG_KEYS)
            fail(f"configuration fields do not match schema; missing={missing}, extra={extra}")

        site_name = _string(values["site_name"], "site_name")
        if SITE_NAME_RE.fullmatch(site_name) is None:
            fail("configuration value site_name is not a safe identifier")

        site_root = _absolute_path(values["site_root"], "site_root")
        try:
            relative_root = site_root.relative_to(SITE_ROOT_BASE)
        except ValueError:
            fail(f"configuration value site_root must be beneath {SITE_ROOT_BASE}")
        if len(relative_root.parts) != 1:
            fail(f"configuration value site_root must be a direct child of {SITE_ROOT_BASE}")

        definitions_path = _absolute_path(values["definitions_path"], "definitions_path")

        raw_entrypoints = values["required_entrypoints"]
        if not isinstance(raw_entrypoints, Sequence) or isinstance(raw_entrypoints, str):
            fail("configuration value required_entrypoints must be a list")
        entrypoints = tuple(
            _relative_path(value, f"required_entrypoints[{index}]")
            for index, value in enumerate(cast(Sequence[object], raw_entrypoints))
        )
        if not entrypoints or len(set(entrypoints)) != len(entrypoints):
            fail("configuration value required_entrypoints must be non-empty and unique")

        raw_checks = values["health_checks"]
        if not isinstance(raw_checks, Sequence) or isinstance(raw_checks, str):
            fail("configuration value health_checks must be a list")
        checks: list[HealthCheck] = []
        for index, value in enumerate(cast(Sequence[object], raw_checks)):
            if not isinstance(value, Mapping):
                fail(f"health_checks[{index}] must be an object")
            check = cast(Mapping[object, object], value)
            if set(check) not in ({"path", "status"}, {"path", "status", "location"}):
                fail(f"health_checks[{index}] has invalid fields")
            path = _string(check["path"], f"health_checks[{index}].path")
            if not path.startswith("/") or path.startswith("//"):
                fail(f"health_checks[{index}].path must be an absolute HTTP path")
            status = _integer(check["status"], f"health_checks[{index}].status", 100, 599)
            raw_location = check.get("location")
            location = None if raw_location is None else _string(
                raw_location, f"health_checks[{index}].location"
            )
            if location is not None and (
                not location.startswith("/") or location.startswith("//")
            ):
                fail(f"health_checks[{index}].location must be an absolute path")
            checks.append(HealthCheck(path, status, location))
        if not checks:
            fail("configuration value health_checks must be non-empty")

        return cls(
            site_name=site_name,
            site_root=site_root,
            definitions_path=definitions_path,
            required_entrypoints=entrypoints,
            health_check_address=_string(values["health_check_address"], "health_check_address"),
            health_check_port=_integer(values["health_check_port"], "health_check_port", 1, 65535),
            staging_health_check_port=_integer(
                values["staging_health_check_port"], "staging_health_check_port", 1, 65535
            ),
            health_check_host=_string(values["health_check_host"], "health_check_host"),
            health_check_timeout=_integer(
                values["health_check_timeout"], "health_check_timeout", 1, 300
            ),
            health_checks=tuple(checks),
        )


@dataclass(frozen=True)
class LinkSnapshot:
    target: str | None


class ReleaseController:
    def __init__(self, config: SiteConfig):
        self.config = config
        self.releases_dir = config.site_root / "releases"
        self.current_link = config.site_root / "current"
        self.staged_link = config.site_root / "staged"
        self.lock_file = config.site_root / ".release.lock"

    @staticmethod
    def validate_release_id(release_id: str) -> str:
        if RELEASE_ID_RE.fullmatch(release_id) is None:
            fail(f"invalid release ID: {release_id!r}")
        return release_id

    def validate_layout(self) -> None:
        for path in (SITE_ROOT_BASE, self.config.site_root, self.releases_dir):
            try:
                info = path.lstat()
            except OSError as error:
                fail(f"required deployment path is unavailable: {path}: {error}")
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                fail(f"required deployment path is not a real directory: {path}")

    def release_directory(self, release_id: str) -> Path:
        self.validate_release_id(release_id)
        release = self.releases_dir / release_id
        try:
            info = release.lstat()
        except OSError as error:
            fail(f"release is not installed: {release_id}: {error}")
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail(f"release path is not a real directory: {release_id}")
        return release

    def inspect_link(self, link: Path, *, required: bool = False) -> str | None:
        try:
            target_text = os.readlink(link)
        except FileNotFoundError:
            if required:
                fail(f"{link.name} is not set")
            return None
        except OSError as error:
            fail(f"cannot read {link.name} symlink: {error}")
        target = PurePosixPath(target_text)
        if target.is_absolute() or len(target.parts) != 2 or target.parts[0] != "releases":
            fail(f"{link.name} symlink does not point directly inside releases")
        release_id = self.validate_release_id(target.parts[1])
        self.release_directory(release_id)
        return release_id

    def snapshot_link(self, link: Path) -> LinkSnapshot:
        release_id = self.inspect_link(link)
        return LinkSnapshot(None if release_id is None else f"releases/{release_id}")

    def replace_link(self, link: Path, release_id: str) -> None:
        self.release_directory(release_id)
        temporary = link.with_name(f".{link.name}.tmp-{os.getpid()}")
        try:
            temporary.unlink(missing_ok=True)
            temporary.symlink_to(Path("releases") / release_id)
            os.replace(temporary, link)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            fail(f"cannot switch {link.name} release: {error}")

    def restore_link(self, link: Path, snapshot: LinkSnapshot) -> None:
        if snapshot.target is None:
            try:
                link.unlink(missing_ok=True)
            except OSError as error:
                fail(f"cannot restore absent {link.name} symlink: {error}")
            return
        release_id = PurePosixPath(snapshot.target).parts[1]
        self.replace_link(link, release_id)

    def initialize_staged(self) -> None:
        if self.inspect_link(self.staged_link) is not None:
            return
        current = self.inspect_link(self.current_link)
        if current is not None:
            self.replace_link(self.staged_link, current)

    def validate_entrypoints(self, release_id: str) -> None:
        release = self.release_directory(release_id)
        for entrypoint in self.config.required_entrypoints:
            path = release
            for component in PurePosixPath(entrypoint).parts:
                path = path / component
                try:
                    info = path.lstat()
                except OSError:
                    fail(f"release is missing required entrypoint: {entrypoint}")
                if stat.S_ISLNK(info.st_mode):
                    fail(f"release entrypoint crosses a symlink: {entrypoint}")
            if not stat.S_ISREG(path.stat().st_mode):
                fail(f"release entrypoint is not a regular file: {entrypoint}")

    def health_check(self, port: int) -> None:
        for check in self.config.health_checks:
            connection = http.client.HTTPConnection(
                self.config.health_check_address,
                port,
                timeout=self.config.health_check_timeout,
            )
            try:
                connection.putrequest("GET", check.path, skip_host=True)
                connection.putheader("Host", self.config.health_check_host)
                connection.endheaders()
                response = connection.getresponse()
                response.read()
            except OSError as error:
                fail(f"health check {check.path} failed: {error}")
            finally:
                connection.close()
            if response.status != check.status:
                fail(
                    f"health check {check.path} returned {response.status}, "
                    f"expected {check.status}"
                )
            if check.location is not None and response.getheader("Location") != check.location:
                fail(f"health check {check.path} returned an unexpected Location header")

    def run_sysupdate(self, release_id: str) -> None:
        command = [
            "/usr/bin/systemd-sysupdate",
            f"--definitions={self.config.definitions_path}",
            "update",
            release_id,
        ]
        try:
            subprocess.run(command, check=True)
        except (OSError, subprocess.CalledProcessError) as error:
            fail(f"systemd-sysupdate rejected release {release_id}: {error}")

    def promote_and_verify(
        self,
        release_id: str,
        current_before: LinkSnapshot,
        staged_before: LinkSnapshot,
    ) -> None:
        self.replace_link(self.current_link, release_id)
        try:
            self.health_check(self.config.health_check_port)
        except ReleaseError as health_error:
            try:
                self.restore_link(self.current_link, current_before)
                self.restore_link(self.staged_link, staged_before)
            except ReleaseError as restore_error:
                fail(f"{health_error}; restoration also failed: {restore_error}")
            raise health_error

    def deploy(self, release_id: str) -> None:
        self.validate_release_id(release_id)
        self.initialize_staged()
        current_before = self.snapshot_link(self.current_link)
        staged_before = self.snapshot_link(self.staged_link)
        self.run_sysupdate(release_id)
        if self.inspect_link(self.staged_link, required=True) != release_id:
            fail("sysupdate did not stage the requested release")
        self.validate_entrypoints(release_id)
        self.health_check(self.config.staging_health_check_port)
        self.promote_and_verify(release_id, current_before, staged_before)

    def rollback(self, release_id: str) -> None:
        self.release_directory(release_id)
        current_before = self.snapshot_link(self.current_link)
        staged_before = self.snapshot_link(self.staged_link)
        self.replace_link(self.staged_link, release_id)
        self.validate_entrypoints(release_id)
        self.health_check(self.config.staging_health_check_port)
        self.promote_and_verify(release_id, current_before, staged_before)

    def list_releases(self, output: TextIO) -> None:
        try:
            paths = sorted(self.releases_dir.iterdir(), key=lambda item: item.name)
        except OSError as error:
            fail(f"cannot list releases: {error}")
        for path in paths:
            if RELEASE_ID_RE.fullmatch(path.name) is not None and path.is_dir() and not path.is_symlink():
                print(path.name, file=output)

    def execute(self, command: str, release_id: str | None, output: TextIO) -> None:
        self.validate_layout()
        if command == "current":
            print(self.inspect_link(self.current_link, required=True), file=output)
            return
        if command == "list":
            self.list_releases(output)
            return
        try:
            with self.lock_file.open("a", encoding="utf-8") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if release_id is None:
                    fail(f"{command} requires a release ID")
                if command == "deploy":
                    self.deploy(release_id)
                elif command == "rollback":
                    self.rollback(release_id)
                else:
                    fail(f"unsupported command: {command}")
        except OSError as error:
            fail(f"cannot acquire release lock: {error}")


def load_config(path: Path) -> SiteConfig:
    try:
        decoded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"cannot load controller configuration: {error}")
    if not isinstance(decoded, dict):
        fail("controller configuration must be a JSON object")
    return SiteConfig.from_mapping(cast(Mapping[str, object], decoded))


def parse_arguments(arguments: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coordinate a static-site release")
    parser.add_argument("--config", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("deploy", "rollback"):
        action = subparsers.add_parser(command)
        action.add_argument("release_id")
    subparsers.add_parser("current")
    subparsers.add_parser("list")
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = parse_arguments(sys.argv[1:] if arguments is None else arguments)
    try:
        config = load_config(cast(Path, parsed.config))
        controller = ReleaseController(config)
        controller.execute(
            cast(str, parsed.command), cast(str | None, getattr(parsed, "release_id", None)), sys.stdout
        )
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
