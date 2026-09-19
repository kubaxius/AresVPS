# ai_generated

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import Mock, call, patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOGIC_PATH = (
    REPOSITORY_ROOT
    / "ansible"
    / "roles"
    / "static_site"
    / "files"
    / "static_site_release.py"
)
LAUNCHER_PATH = (
    REPOSITORY_ROOT
    / "ansible"
    / "roles"
    / "static_site"
    / "templates"
    / "static_site_release_launcher.py.j2"
)


class StaticSiteReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "example-site"
        (self.root / "incoming").mkdir(parents=True)
        (self.root / "releases").mkdir()
        self.module = self.load_logic()
        self.module.SITE_ROOT_BASE = Path(self.temporary.name)
        self.config = self.module.SiteConfig.from_mapping(self.config_values())
        self.manager = self.module.ReleaseManager(self.config)
        self.manager.normalize_release = self.normalize_for_test

    def config_values(self) -> dict[str, object]:
        return {
            "site_name": "example",
            "site_root": str(self.root),
            "web_group": "web-readers",
            "manifest_schema_version": 7,
            "release_retention": 2,
            "archive_max_members": 20,
            "archive_max_expanded_size": 4096,
            "required_entrypoints": [
                "index.html",
                "de/index.html",
                "fr/index.html",
            ],
            "health_check_address": "127.0.0.2",
            "health_check_port": 8080,
            "health_check_host": "example.test",
            "health_check_timeout": 3,
            "health_checks": [
                {"path": "/", "status": 308, "location": "/de/"},
                {"path": "/de/", "status": 200},
            ],
        }

    @staticmethod
    def load_logic():
        spec = importlib.util.spec_from_file_location("static_site_release", LOGIC_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # Dataclasses inspect their defining module while the class is created.
        import sys

        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def normalize_for_test(release_dir: Path) -> None:
        for path in release_dir.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)

    def manifest(self, release_number: int = 1) -> tuple[dict[str, object], bytes]:
        commit = f"{release_number:040x}"
        tag = f"v1.2.{release_number}"
        manifest = {
            "schema_version": 7,
            "site": "example",
            "tag": tag,
            "commit": commit,
            "release_id": f"{tag}-{commit[:12]}",
        }
        return manifest, (json.dumps(manifest, separators=(",", ":")) + "\n").encode()

    def artifact(
        self,
        release_number: int = 1,
        *,
        members: dict[str, bytes] | None = None,
        link: str | None = None,
    ) -> tuple[Path, Path, Path, str]:
        manifest, manifest_bytes = self.manifest(release_number)
        release_id = str(manifest["release_id"])
        archive = self.root / "incoming" / f"example-{release_id}.tar.gz"
        payload = members or {
            "index.html": b"root",
            "de/index.html": b"de",
            "fr/index.html": b"fr",
            ".release-manifest.json": manifest_bytes,
        }
        with tarfile.open(archive, "w:gz") as bundle:
            for name, contents in payload.items():
                info = tarfile.TarInfo(name)
                info.size = len(contents)
                bundle.addfile(info, io.BytesIO(contents))
            if link is not None:
                info = tarfile.TarInfo(link)
                info.type = tarfile.SYMTYPE
                info.linkname = "index.html"
                bundle.addfile(info)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        checksum = archive.with_name(f"{archive.name}.sha256")
        checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
        manifest_path = self.root / "incoming" / f"example-{release_id}.manifest.json"
        manifest_path.write_bytes(manifest_bytes)
        return archive, checksum, manifest_path, release_id

    def install_artifact(self, release_number: int = 1) -> str:
        archive, checksum, manifest, release_id = self.artifact(release_number)
        self.manager.install(str(archive), str(checksum), str(manifest))
        return release_id

    def test_custom_rendered_configuration_drives_installation(self) -> None:
        release_id = self.install_artifact()

        release = self.root / "releases" / release_id
        self.assertTrue((release / "de/index.html").is_file())
        self.assertTrue((release / "fr/index.html").is_file())
        self.assertTrue((release / ".release-archive.sha256").is_file())
        self.assertEqual(self.manager.config.site_name, "example")
        self.assertEqual(self.manager.config.health_check_host, "example.test")
        self.assertNotIn("bearworks", LOGIC_PATH.read_text(encoding="utf-8").lower())

    def test_configuration_rejects_roots_outside_managed_base(self) -> None:
        values = self.config_values()
        values["site_root"] = "/tmp/example"
        with self.assertRaisesRegex(self.module.ReleaseError, "beneath"):
            self.module.SiteConfig.from_mapping(values)

    def test_layout_rejects_site_root_symlink(self) -> None:
        other_root = Path(self.temporary.name) / "real-site"
        self.root.rename(other_root)
        self.root.symlink_to(other_root, target_is_directory=True)
        with self.assertRaisesRegex(self.module.ReleaseError, "real directory"):
            self.manager.validate_layout()

    def test_identical_retry_succeeds_and_conflicting_duplicate_fails(self) -> None:
        archive, checksum, manifest, release_id = self.artifact()
        self.manager.install(str(archive), str(checksum), str(manifest))
        self.manager.install(str(archive), str(checksum), str(manifest))

        (self.root / "releases" / release_id / ".release-archive.sha256").write_text(
            "0" * 64 + "\n", encoding="ascii"
        )
        with self.assertRaisesRegex(self.module.ReleaseError, "different content"):
            self.manager.install(str(archive), str(checksum), str(manifest))

    def test_invalid_checksum_and_manifest_relationship_are_rejected(self) -> None:
        archive, checksum, manifest_path, _ = self.artifact()
        checksum.write_text(f"{'0' * 64}  {archive.name}\n", encoding="ascii")
        with self.assertRaisesRegex(self.module.ReleaseError, "checksum"):
            self.manager.install(str(archive), str(checksum), str(manifest_path))

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["site"] = "another-site"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(self.module.ReleaseError, "site"):
            self.manager.install(str(archive), str(checksum), str(manifest_path))

    def test_unsafe_and_incomplete_archives_leave_no_release(self) -> None:
        cases = (
            ({"../outside": b"bad"}, None, "unsafe archive path"),
            ({"index.html": b"root"}, None, "release-manifest"),
            (None, "linked", "unsupported member"),
        )
        for index, (members, link, message) in enumerate(cases, start=2):
            with self.subTest(message=message):
                archive, checksum, manifest, release_id = self.artifact(
                    index, members=members, link=link
                )
                with self.assertRaisesRegex(self.module.ReleaseError, message):
                    self.manager.install(str(archive), str(checksum), str(manifest))
                self.assertFalse((self.root / "releases" / release_id).exists())
                self.assertEqual(list((self.root / "releases").glob(".install-*")), [])

    def test_archive_member_and_size_limits_are_enforced(self) -> None:
        archive, _, _, _ = self.artifact()
        with tarfile.open(archive, "r:gz") as bundle:
            manager = self.module.ReleaseManager(
                replace(self.config, archive_max_members=1)
            )
            with self.assertRaisesRegex(self.module.ReleaseError, "members"):
                manager.inspect_archive(bundle)

        archive, _, _, _ = self.artifact(2)
        with tarfile.open(archive, "r:gz") as bundle:
            manager = self.module.ReleaseManager(
                replace(self.config, archive_max_expanded_size=1)
            )
            with self.assertRaisesRegex(self.module.ReleaseError, "expands beyond"):
                manager.inspect_archive(bundle)

    def test_activation_and_rollback_restore_or_switch_current(self) -> None:
        first = self.install_artifact(1)
        second = self.install_artifact(2)
        with patch.object(self.manager, "health_check"):
            self.manager.activate(first)
        self.assertEqual(self.manager.current_release(), first)

        with patch.object(
            self.manager,
            "health_check",
            side_effect=self.module.ReleaseError("unhealthy"),
        ):
            with self.assertRaisesRegex(self.module.ReleaseError, "unhealthy"):
                self.manager.activate(second)
        self.assertEqual(self.manager.current_release(), first)

        with patch.object(self.manager, "health_check"):
            self.manager.activate(second)
            self.manager.activate(first)
        self.assertEqual(self.manager.current_release(), first)

    def test_retention_keeps_active_previous_and_newest_inactive(self) -> None:
        releases = [self.install_artifact(number) for number in range(1, 5)]
        for index, release_id in enumerate(releases):
            path = self.root / "releases" / release_id
            timestamp = 100 + index
            path.touch()
            path.chmod(0o750)
            os.utime(path, ns=(timestamp, timestamp))

        self.manager.prune_releases(releases[0], releases[1])

        remaining = {path.name for path in (self.root / "releases").iterdir()}
        self.assertEqual(remaining, {releases[0], releases[1], releases[3]})

    def test_failed_first_activation_removes_current_link(self) -> None:
        release_id = self.install_artifact()
        with patch.object(
            self.manager,
            "health_check",
            side_effect=self.module.ReleaseError("unhealthy"),
        ):
            with self.assertRaisesRegex(self.module.ReleaseError, "unhealthy"):
                self.manager.activate(release_id)

        self.assertFalse((self.root / "current").exists())
        self.assertFalse((self.root / "current").is_symlink())

    def test_health_checks_use_rendered_endpoint_and_expectations(self) -> None:
        response = Mock()
        response.status = 308
        response.getheader.return_value = "/de/"
        second_response = Mock()
        second_response.status = 200
        second_response.getheader.return_value = None
        connection = Mock()
        connection.getresponse.side_effect = [response, second_response]

        with patch.object(
            self.module.http.client,
            "HTTPConnection",
            return_value=connection,
        ) as connection_class:
            self.manager.health_check()

        self.assertEqual(connection_class.call_count, 2)
        connection_class.assert_any_call("127.0.0.2", 8080, timeout=3)
        self.assertEqual(
            connection.putrequest.call_args_list,
            [
                call("GET", "/", skip_host=True),
                call("GET", "/de/", skip_host=True),
            ],
        )

class StaticSiteAnsibleTests(unittest.TestCase):
    def render_launcher(self, directory: Path, site_name: str) -> Path:
        values: dict[str, object] = {
            "static_site_name": site_name,
            "static_site_root": f"/srv/www/{site_name}",
            "static_site_web_group": "www-data",
            "static_site_manifest_schema_version": 1,
            "static_site_release_retention": 5,
            "static_site_archive_max_members": 10000,
            "static_site_archive_max_expanded_size": 536870912,
            "static_site_required_entrypoints": ["index.html", "en/index.html"],
            "static_site_health_check_address": "127.0.0.1",
            "static_site_health_check_port": 80,
            "static_site_health_check_host": f"{site_name}.test",
            "static_site_health_check_timeout": 5,
            "static_site_health_checks": [{"path": "/en/", "status": 200}],
        }
        source = LAUNCHER_PATH.read_text(encoding="utf-8")
        for name, value in values.items():
            source = source.replace(
                f"{{{{ {name} | to_json | to_json }}}}",
                json.dumps(json.dumps(value)),
            )
            source = source.replace(f"{{{{ {name} | to_json }}}}", json.dumps(value))
            source = source.replace(f"{{{{ {name} | int }}}}", str(value))
        library = directory / "library"
        library.mkdir(exist_ok=True)
        shutil.copyfile(LOGIC_PATH, library / "static_site_release.py")
        source = source.replace("/usr/local/lib/static-site-release", str(library))
        self.assertNotIn("{{", source)
        launcher = directory / f"{site_name}-release"
        launcher.write_text(source, encoding="utf-8")
        launcher.chmod(0o755)
        return launcher

    def test_two_launchers_share_logic_and_ignore_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            hostile = directory / "hostile"
            hostile.mkdir()
            (hostile / "static_site_release.py").write_text(
                "raise RuntimeError('loaded attacker-controlled module')\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(hostile)
            for site_name in ("first-site", "second-site"):
                launcher = self.render_launcher(directory, site_name)
                result = subprocess.run(
                    [str(launcher), "--help"],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(site_name, result.stdout)

    def test_role_renders_and_restricts_configured_helper(self) -> None:
        tasks = (
            REPOSITORY_ROOT
            / "ansible/roles/static_site/tasks/main.yml"
        ).read_text(encoding="utf-8")
        defaults = (
            REPOSITORY_ROOT
            / "ansible/roles/static_site/defaults/main.yml"
        ).read_text(encoding="utf-8")

        launcher = LAUNCHER_PATH.read_text(encoding="utf-8")
        logic = LOGIC_PATH.read_text(encoding="utf-8")

        self.assertIn('src: "static_site_release.py"', tasks)
        self.assertIn('mode: "0644"', tasks)
        self.assertIn('src: "static_site_release_launcher.py.j2"', tasks)
        self.assertIn('dest: "/usr/local/sbin/{{ static_site_script_file_name }}"', tasks)
        self.assertIn('mode: "0755"', tasks)
        self.assertIn("NOPASSWD:", tasks)
        self.assertIn("#!/usr/bin/python3 -I", launcher)
        self.assertIn("from static_site_release import main", launcher)
        self.assertIn("main(SITE_CONFIG)", launcher)
        self.assertNotIn("{{", logic)
        self.assertIn('static_site_name: "bearworks"', defaults)
        self.assertIn('static_site_root: "/srv/www/{{ static_site_name }}"', defaults)
        self.assertIn('static_site_domain: "bearworks.pl"', defaults)


if __name__ == "__main__":
    unittest.main()
