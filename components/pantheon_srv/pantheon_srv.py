#!/usr/bin/python3 -I
# ai_generated

"""Manage Pantheon services installed on a server.

Run the agent as root with a site-specific configuration file::

    pantheon-srv site SITE update
    pantheon-srv site SITE list
    pantheon-srv site SITE activate RELEASE_ID

Ansible invokes ``update`` after configuring every declared site. Operators use
``list`` to inspect retained releases and ``activate`` to switch a site
atomically to an already installed release.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from typing import NoReturn, TextIO, cast


SITE_ROOT_BASE = Path("/srv/www")
SITE_CONFIG_ROOT = Path("/etc/pantheon/sites.d")
SYSUPDATE_PATH = Path("/usr/lib/systemd/systemd-sysupdate")
RELEASE_ID_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-[0-9a-f]{12}$"
)
SITE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
CONFIG_KEYS = {
    "site_name",
    "site_root",
    "definitions_path",
    "required_entrypoints",
}


class ReleaseError(Exception):
    """A release operation failed without exposing an implementation traceback."""


def fail(message: str) -> NoReturn:
    """Abort the current operation with a user-facing release error.

    Args:
        message: Explanation printed by the command-line entry point.

    Raises:
        ReleaseError: Always raised with ``message``.
    """

    raise ReleaseError(message)


def _string(value: object, name: str) -> str:
    """Validate and return a non-empty configuration string.

    Control characters that could make logs or subprocess arguments ambiguous
    are rejected.

    Args:
        value: Untrusted value decoded from the JSON configuration.
        name: Configuration field name used in validation errors.

    Returns:
        The validated string.

    Raises:
        ReleaseError: If ``value`` is empty, is not a string, or contains an
            unsafe control character.
    """

    if not isinstance(value, str) or not value:
        fail(f"configuration value {name} must be a non-empty string")
    if any(character in value for character in ("\x00", "\r", "\n")):
        fail(f"configuration value {name} contains unsafe characters")
    return value


def _absolute_path(value: object, name: str) -> Path:
    """Validate and return a normalized absolute configuration path.

    Args:
        value: Untrusted path value decoded from JSON.
        name: Configuration field name used in validation errors.

    Returns:
        A normalized absolute ``Path``.

    Raises:
        ReleaseError: If the value is not an absolute, normalized path.
    """

    text = _string(value, name)
    path = Path(text)
    if not path.is_absolute() or Path(os.path.normpath(text)) != path:
        fail(f"configuration value {name} must be a normalized absolute path")
    return path


def _relative_path(value: object, name: str) -> str:
    """Validate a release-relative path without parent traversal.

    Args:
        value: Untrusted path value decoded from JSON.
        name: Configuration field name used in validation errors.

    Returns:
        The normalized relative path as text.

    Raises:
        ReleaseError: If the path is absolute, empty, non-normalized, or
            contains a parent-directory component.
    """

    text = _string(value, name)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or str(path) != text or text == ".":
        fail(f"configuration value {name} must be a normalized relative path")
    return text


@dataclass(frozen=True)
class SiteConfig:
    site_name: str
    site_root: Path
    definitions_path: Path
    required_entrypoints: tuple[str, ...]

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> SiteConfig:
        """Create a strictly validated site configuration.

        The schema is closed: callers must provide every supported field and
        may not add unknown fields. Filesystem paths must match the locations
        derived from the site name by Ansible.

        Args:
            values: JSON object containing the site configuration.

        Returns:
            An immutable validated ``SiteConfig``.

        Raises:
            ReleaseError: If the schema, site identity, paths, or required
                entrypoints are invalid.
        """

        if set(values) != CONFIG_KEYS:
            missing = sorted(CONFIG_KEYS - set(values))
            extra = sorted(set(values) - CONFIG_KEYS)
            fail(f"configuration fields do not match schema; missing={missing}, extra={extra}")

        site_name = _string(values["site_name"], "site_name")
        if SITE_NAME_RE.fullmatch(site_name) is None:
            fail("configuration value site_name is not a safe identifier")

        site_root = _absolute_path(values["site_root"], "site_root")
        expected_site_root = SITE_ROOT_BASE / site_name
        if site_root != expected_site_root:
            fail(f"configuration value site_root must be {expected_site_root}")

        definitions_path = _absolute_path(values["definitions_path"], "definitions_path")
        expected_definitions_path = Path(f"/etc/sysupdate.{site_name}.d")
        if definitions_path != expected_definitions_path:
            fail(
                "configuration value definitions_path must be "
                f"{expected_definitions_path}"
            )

        raw_entrypoints = values["required_entrypoints"]
        if not isinstance(raw_entrypoints, Sequence) or isinstance(raw_entrypoints, str):
            fail("configuration value required_entrypoints must be a list")
        entrypoints = tuple(
            _relative_path(value, f"required_entrypoints[{index}]")
            for index, value in enumerate(cast(Sequence[object], raw_entrypoints))
        )
        if not entrypoints or len(set(entrypoints)) != len(entrypoints):
            fail("configuration value required_entrypoints must be non-empty and unique")

        return cls(
            site_name=site_name,
            site_root=site_root,
            definitions_path=definitions_path,
            required_entrypoints=entrypoints,
        )


class ReleaseAgent:
    def __init__(self, config: SiteConfig):
        """Initialize filesystem paths for one configured site.

        Args:
            config: Validated site configuration loaded from JSON.
        """

        self.config = config
        self.releases_dir = config.site_root / "releases"
        self.current_link = config.site_root / "current"
        self.staged_link = config.site_root / "staged"
        self.lock_file = config.site_root / ".release.lock"

    @staticmethod
    def validate_release_id(release_id: str) -> str:
        """Validate a version-and-commit release identifier.

        Args:
            release_id: Candidate identifier such as
                ``v1.2.3-0123456789ab``.

        Returns:
            The unchanged validated identifier.

        Raises:
            ReleaseError: If the identifier does not match the required
                semantic-version and twelve-character commit format.
        """

        if RELEASE_ID_RE.fullmatch(release_id) is None:
            fail(f"invalid release ID: {release_id!r}")
        return release_id

    @staticmethod
    def release_sort_key(release_id: str) -> tuple[int, int, int, str]:
        """Return a stable semantic-version sort key for a release ID.

        Args:
            release_id: Valid version-and-commit release identifier.

        Returns:
            Major, minor, patch, and full-ID values suitable for sorting.

        Raises:
            ReleaseError: If ``release_id`` is malformed.
        """

        match = RELEASE_ID_RE.fullmatch(release_id)
        if match is None:
            fail(f"invalid release ID: {release_id!r}")
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)), release_id)

    def validate_layout(self) -> None:
        """Require the configured deployment roots to be real directories.

        Rejecting symlinked roots prevents release operations from escaping
        the Ansible-managed filesystem boundary.

        Raises:
            ReleaseError: If a required directory is missing, inaccessible,
                not a directory, or itself a symlink.
        """

        for path in (SITE_ROOT_BASE, self.config.site_root, self.releases_dir):
            try:
                info = path.lstat()
            except OSError as error:
                fail(f"required deployment path is unavailable: {path}: {error}")
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                fail(f"required deployment path is not a real directory: {path}")

    def release_directory(self, release_id: str) -> Path:
        """Resolve an installed release without following a directory symlink.

        Args:
            release_id: Release identifier to resolve below ``releases/``.

        Returns:
            Path to the installed release directory.

        Raises:
            ReleaseError: If the ID is malformed or the installed path is
                missing, not a directory, or a symlink.
        """

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
        """Read and validate a managed release symlink.

        A valid link is relative and points directly to
        ``releases/RELEASE_ID`` within the configured site root.

        Args:
            link: ``current`` or ``staged`` symlink to inspect.
            required: Whether an absent link is an error.

        Returns:
            The selected release ID, or ``None`` when an optional link is
            absent.

        Raises:
            ReleaseError: If the link is required but absent, cannot be read,
                has an unsafe target, or selects an invalid release.
        """

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

    def replace_link(self, link: Path, release_id: str) -> None:
        """Atomically point a managed symlink at an installed release.

        The replacement is prepared beside the destination and committed with
        ``os.replace`` so readers see either the old or new target.

        Args:
            link: Managed symlink to replace.
            release_id: Installed release that should become the target.

        Raises:
            ReleaseError: If the release is invalid or the atomic replacement
                cannot be completed.
        """

        self.release_directory(release_id)
        temporary = link.with_name(f".{link.name}.tmp-{os.getpid()}")
        try:
            temporary.unlink(missing_ok=True)
            temporary.symlink_to(Path("releases") / release_id)
            os.replace(temporary, link)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            fail(f"cannot switch {link.name} release: {error}")

    def restore_link(self, link: Path, release_id: str | None) -> None:
        """Restore a managed link to a previous release or absent state.

        Args:
            link: Managed symlink to restore.
            release_id: Previous release ID, or ``None`` if the link was
                previously absent.

        Raises:
            ReleaseError: If restoration cannot be completed safely.
        """

        if release_id is not None:
            self.replace_link(link, release_id)
            return
        try:
            link.unlink(missing_ok=True)
        except OSError as error:
            fail(f"cannot restore absent {link.name} symlink: {error}")

    def validate_entrypoints(self, release_id: str) -> None:
        """Require every configured entrypoint to be a regular file.

        Each path component is inspected with ``lstat``. Symlinks are rejected
        so an archive cannot satisfy an entrypoint by escaping its release
        directory.

        Args:
            release_id: Installed release whose contents should be checked.

        Raises:
            ReleaseError: If an entrypoint is missing, crosses a symlink, or
                does not end at a regular file.
        """

        release = self.release_directory(release_id)
        for entrypoint in self.config.required_entrypoints:
            path = release
            info: os.stat_result | None = None
            for component in PurePosixPath(entrypoint).parts:
                path = path / component
                try:
                    info = path.lstat()
                except OSError:
                    fail(f"release is missing required entrypoint: {entrypoint}")
                if stat.S_ISLNK(info.st_mode):
                    fail(f"release entrypoint crosses a symlink: {entrypoint}")
            if info is None or not stat.S_ISREG(info.st_mode):
                fail(f"release entrypoint is not a regular file: {entrypoint}")

    def installed_release_ids(self) -> set[str]:
        """Return valid release directories installed for this site.

        Entries with malformed names, non-directory entries, and symlinked
        directories are ignored.

        Returns:
            Set of installed release identifiers.

        Raises:
            ReleaseError: If the releases directory cannot be listed.
        """

        try:
            paths = tuple(self.releases_dir.iterdir())
        except OSError as error:
            fail(f"cannot list releases: {error}")
        return {
            path.name
            for path in paths
            if RELEASE_ID_RE.fullmatch(path.name) is not None
            and path.is_dir()
            and not path.is_symlink()
        }

    def run_sysupdate(self) -> None:
        """Ask systemd-sysupdate to install the latest signed release.

        Sysupdate uses the configured definition directory to discover the
        GitHub source, verify its signed checksum manifest, extract the
        archive, update ``staged``, and apply retention.

        Raises:
            ReleaseError: If sysupdate cannot start or rejects the update.
        """

        try:
            subprocess.run(
                [
                    str(SYSUPDATE_PATH),
                    f"--definitions={self.config.definitions_path}",
                    "update",
                ],
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            fail(f"systemd-sysupdate rejected the latest release: {error}")

    def update(self, output: TextIO) -> None:
        """Install and activate one newly published release.

        The active release is staged before sysupdate runs so retention cannot
        remove it. A no-op update preserves a manual activation. Exactly one
        newly installed release must appear before entrypoint validation and
        atomic promotion are attempted.

        Args:
            output: Text stream receiving the operation result.

        Raises:
            ReleaseError: If sysupdate fails, produces an unexpected state,
                the new release is invalid, or no initial release is available.
        """

        current_before = self.inspect_link(self.current_link)
        staged_before = self.inspect_link(self.staged_link)
        self.restore_link(self.staged_link, current_before)
        installed_before = self.installed_release_ids()

        try:
            self.run_sysupdate()
        except ReleaseError:
            self.restore_link(self.staged_link, staged_before)
            raise

        newly_installed = self.installed_release_ids() - installed_before
        if not newly_installed:
            self.restore_link(self.staged_link, staged_before)
            if current_before is None:
                fail("no new release was installed and current is not set")
            print("No new release is available.", file=output)
            return
        if len(newly_installed) != 1:
            self.restore_link(self.staged_link, staged_before)
            fail("sysupdate installed an unexpected number of releases")

        release_id = newly_installed.pop()
        try:
            if self.inspect_link(self.staged_link, required=True) != release_id:
                fail("sysupdate did not stage the newly installed release")
            self.validate_entrypoints(release_id)
            self.replace_link(self.current_link, release_id)
        except ReleaseError:
            self.restore_link(self.staged_link, staged_before)
            raise
        print(f"Activated {release_id}.", file=output)

    def activate(self, release_id: str, output: TextIO) -> None:
        """Atomically activate an already installed release.

        Args:
            release_id: Installed release to select for both ``staged`` and
                ``current``.
            output: Text stream receiving the operation result.

        Raises:
            ReleaseError: If the release is absent or invalid, or either link
                cannot be switched safely.
        """

        self.validate_entrypoints(release_id)
        staged_before = self.inspect_link(self.staged_link)
        self.replace_link(self.staged_link, release_id)
        try:
            self.replace_link(self.current_link, release_id)
        except ReleaseError:
            self.restore_link(self.staged_link, staged_before)
            raise
        print(f"Activated {release_id}.", file=output)

    def list_releases(self, output: TextIO) -> None:
        """Print installed releases in version order.

        The active release is prefixed with ``*``; inactive releases are
        prefixed with a space.

        Args:
            output: Text stream receiving the release list.

        Raises:
            ReleaseError: If release state cannot be inspected.
        """

        current = self.inspect_link(self.current_link)
        for release_id in sorted(self.installed_release_ids(), key=self.release_sort_key):
            marker = "*" if release_id == current else " "
            print(f"{marker} {release_id}", file=output)

    def execute(self, command: str, release_id: str | None, output: TextIO) -> None:
        """Dispatch one validated CLI operation.

        Mutating commands take an exclusive per-site file lock. ``list`` is
        read-only and does not wait for that lock.

        Args:
            command: One of ``update``, ``activate``, or ``list``.
            release_id: Required target for ``activate``; otherwise ``None``.
            output: Text stream receiving command output.

        Raises:
            ReleaseError: If the filesystem layout, command, lock, or requested
                operation is invalid.
        """

        self.validate_layout()
        if command == "list":
            self.list_releases(output)
            return
        try:
            with self.lock_file.open("a", encoding="utf-8") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if command == "update":
                    self.update(output)
                elif command == "activate" and release_id is not None:
                    self.activate(release_id, output)
                else:
                    fail(f"unsupported command: {command}")
        except OSError as error:
            fail(f"cannot acquire release lock: {error}")


def validate_site_name(site_name: str) -> str:
    """Validate a site name before using it to locate configuration.

    Args:
        site_name: Name supplied through the command line.

    Returns:
        The unchanged validated site name.

    Raises:
        ReleaseError: If the name could escape the configuration directory or
            cannot be used as a Pantheon site identifier.
    """

    if SITE_NAME_RE.fullmatch(site_name) is None:
        fail(f"invalid site name: {site_name!r}")
    return site_name


def load_site_config(site_name: str) -> SiteConfig:
    """Load one named site's Ansible-managed JSON configuration.

    Args:
        site_name: Valid site name used to select
            ``/etc/pantheon/sites.d/SITE.json``.

    Returns:
        Validated immutable site configuration.

    Raises:
        ReleaseError: If the site name is invalid, the file cannot be read,
            the JSON is malformed, the schema is invalid, or the stored site
            name does not match the requested name.
    """

    validated_name = validate_site_name(site_name)
    path = SITE_CONFIG_ROOT / f"{validated_name}.json"
    try:
        decoded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"cannot load configuration for site {validated_name!r}: {error}")
    if not isinstance(decoded, dict):
        fail(f"configuration for site {validated_name!r} must be a JSON object")
    config = SiteConfig.from_mapping(cast(Mapping[str, object], decoded))
    if config.site_name != validated_name:
        fail(f"configuration for site {validated_name!r} contains a different site name")
    return config


def parse_arguments(arguments: Sequence[str]) -> argparse.Namespace:
    """Parse Pantheon server command-line arguments.

    Args:
        arguments: Arguments excluding the executable name.

    Returns:
        Namespace containing the command group, site name, site operation, and
        optional release ID.
    """

    parser = argparse.ArgumentParser(
        prog="pantheon-srv",
        description="Manage services configured on a Pantheon server",
        epilog=(
            "examples:\n"
            "  pantheon-srv site bearworks update\n"
            "  pantheon-srv site bearworks list\n"
            "  pantheon-srv site bearworks activate v1.2.3-0123456789ab"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    command_parsers = parser.add_subparsers(dest="command_group", required=True)
    site = command_parsers.add_parser("site", help="Manage one configured static site")
    site.add_argument("site_name", metavar="SITE")
    site_commands = site.add_subparsers(dest="site_command", required=True)
    site_commands.add_parser("update", help="Install and activate the latest release")
    site_commands.add_parser("list", help="List installed releases")
    activate = site_commands.add_parser(
        "activate", help="Activate an already installed release"
    )
    activate.add_argument("release_id")
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the Pantheon server command-line interface.

    Args:
        arguments: Optional explicit arguments for embedding or manual
            invocation. Defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` after a successful command or ``1`` after a controlled release
        error. Argument errors retain argparse's standard exit behavior.
    """

    parsed = parse_arguments(sys.argv[1:] if arguments is None else arguments)
    try:
        if cast(str, parsed.command_group) != "site":
            fail(f"unsupported command group: {parsed.command_group}")
        config = load_site_config(cast(str, parsed.site_name))
        agent = ReleaseAgent(config)
        agent.execute(
            cast(str, parsed.site_command),
            cast(str | None, getattr(parsed, "release_id", None)),
            sys.stdout,
        )
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
