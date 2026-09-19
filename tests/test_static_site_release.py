# ai_generated

import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, call, patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ROLE_ROOT = REPOSITORY_ROOT / "ansible/roles/static_site"
CONTROLLER_PATH = ROLE_ROOT / "files/static_site_release_control.py"


def load_controller():
    spec = importlib.util.spec_from_file_location("static_site_release_control", CONTROLLER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class StaticSiteReleaseControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "example"
        (self.root / "releases").mkdir(parents=True)
        self.module = load_controller()
        setattr(self.module, "SITE_ROOT_BASE", self.base)
        self.config = self.module.SiteConfig.from_mapping(self.config_values())
        self.controller = self.module.ReleaseController(self.config)

    def config_values(self) -> dict[str, object]:
        return {
            "site_name": "example",
            "site_root": str(self.root),
            "definitions_path": "/etc/sysupdate.example.d",
            "required_entrypoints": ["index.html", "en/index.html"],
            "health_check_address": "127.0.0.2",
            "health_check_port": 8080,
            "staging_health_check_port": 18081,
            "health_check_host": "example.test",
            "health_check_timeout": 3,
            "health_checks": [
                {"path": "/", "status": 308, "location": "/en/"},
                {"path": "/en/", "status": 200},
            ],
        }

    @staticmethod
    def release_id(number: int) -> str:
        return f"v1.2.{number}-{number:012x}"

    def create_release(self, number: int, *, complete: bool = True) -> str:
        release_id = self.release_id(number)
        release = self.root / "releases" / release_id
        release.mkdir()
        (release / "index.html").write_text("root", encoding="utf-8")
        if complete:
            (release / "en").mkdir()
            (release / "en/index.html").write_text("en", encoding="utf-8")
        return release_id

    def link(self, name: str, release_id: str) -> None:
        (self.root / name).symlink_to(Path("releases") / release_id)

    def test_configuration_is_exact_and_typed(self) -> None:
        values = self.config_values()
        values["unexpected"] = True
        with self.assertRaisesRegex(self.module.ReleaseError, "schema"):
            self.module.SiteConfig.from_mapping(values)

        values = self.config_values()
        values["site_root"] = "/tmp/outside"
        with self.assertRaisesRegex(self.module.ReleaseError, "beneath"):
            self.module.SiteConfig.from_mapping(values)

        values = self.config_values()
        values["required_entrypoints"] = ["../escape"]
        with self.assertRaisesRegex(self.module.ReleaseError, "relative path"):
            self.module.SiteConfig.from_mapping(values)

    def test_release_id_and_symlink_boundaries_are_strict(self) -> None:
        release_id = self.create_release(1)
        self.link("current", release_id)
        self.assertEqual(self.controller.inspect_link(self.root / "current"), release_id)

        (self.root / "current").unlink()
        (self.root / "current").symlink_to(f"../{release_id}")
        with self.assertRaisesRegex(self.module.ReleaseError, "directly inside"):
            self.controller.inspect_link(self.root / "current")

        with self.assertRaisesRegex(self.module.ReleaseError, "invalid release ID"):
            self.controller.validate_release_id("v1.2.3-ABC")

    def test_entrypoints_reject_missing_files_and_symlink_components(self) -> None:
        incomplete = self.create_release(1, complete=False)
        with self.assertRaisesRegex(self.module.ReleaseError, "missing required"):
            self.controller.validate_entrypoints(incomplete)

        release_id = self.create_release(2)
        (self.root / "releases" / release_id / "en/index.html").unlink()
        (self.root / "releases" / release_id / "en/index.html").symlink_to("../index.html")
        with self.assertRaisesRegex(self.module.ReleaseError, "crosses a symlink"):
            self.controller.validate_entrypoints(release_id)

    def test_deploy_initializes_staged_runs_sysupdate_and_promotes(self) -> None:
        old = self.create_release(1)
        new = self.create_release(2)
        self.link("current", old)

        def stage(_release_id: str) -> None:
            self.controller.replace_link(self.root / "staged", new)

        with patch.object(self.controller, "run_sysupdate", side_effect=stage) as update, patch.object(
            self.controller, "health_check"
        ) as health:
            self.controller.execute("deploy", new, io.StringIO())

        update.assert_called_once_with(new)
        self.assertEqual(
            health.call_args_list,
            [call(self.config.staging_health_check_port), call(self.config.health_check_port)],
        )
        self.assertEqual(self.controller.inspect_link(self.root / "current"), new)
        self.assertEqual(self.controller.inspect_link(self.root / "staged"), new)

    def test_staging_failure_never_changes_current(self) -> None:
        old = self.create_release(1)
        new = self.create_release(2)
        self.link("current", old)
        self.link("staged", old)

        def stage(_release_id: str) -> None:
            self.controller.replace_link(self.root / "staged", new)

        with patch.object(self.controller, "run_sysupdate", side_effect=stage), patch.object(
            self.controller, "health_check", side_effect=self.module.ReleaseError("unhealthy")
        ):
            with self.assertRaisesRegex(self.module.ReleaseError, "unhealthy"):
                self.controller.execute("deploy", new, io.StringIO())

        self.assertEqual(self.controller.inspect_link(self.root / "current"), old)

    def test_post_promotion_failure_restores_both_links(self) -> None:
        old = self.create_release(1)
        new = self.create_release(2)
        self.link("current", old)
        self.link("staged", old)

        def stage(_release_id: str) -> None:
            self.controller.replace_link(self.root / "staged", new)

        with patch.object(self.controller, "run_sysupdate", side_effect=stage), patch.object(
            self.controller,
            "health_check",
            side_effect=[None, self.module.ReleaseError("production unhealthy")],
        ):
            with self.assertRaisesRegex(self.module.ReleaseError, "production unhealthy"):
                self.controller.execute("deploy", new, io.StringIO())

        self.assertEqual(self.controller.inspect_link(self.root / "current"), old)
        self.assertEqual(self.controller.inspect_link(self.root / "staged"), old)

    def test_rollback_stages_checks_and_promotes_retained_release(self) -> None:
        old = self.create_release(1)
        active = self.create_release(2)
        self.link("current", active)
        self.link("staged", active)
        with patch.object(self.controller, "health_check") as health:
            self.controller.execute("rollback", old, io.StringIO())
        self.assertEqual(self.controller.inspect_link(self.root / "current"), old)
        self.assertEqual(self.controller.inspect_link(self.root / "staged"), old)
        self.assertEqual(health.call_count, 2)

    def test_mutations_take_the_per_site_flock(self) -> None:
        release_id = self.create_release(1)
        self.link("current", release_id)
        self.link("staged", release_id)
        with patch.object(self.module.fcntl, "flock") as flock, patch.object(
            self.controller, "run_sysupdate"
        ), patch.object(self.controller, "health_check"):
            self.controller.execute("deploy", release_id, io.StringIO())
        flock.assert_called_once()
        self.assertEqual(flock.call_args.args[1], self.module.fcntl.LOCK_EX)

    def test_health_checks_use_configured_endpoint_and_host(self) -> None:
        redirect = Mock(status=308)
        redirect.getheader.return_value = "/en/"
        redirect.read.return_value = b""
        page = Mock(status=200)
        page.getheader.return_value = None
        page.read.return_value = b""
        first_connection = Mock()
        first_connection.getresponse.return_value = redirect
        second_connection = Mock()
        second_connection.getresponse.return_value = page
        with patch.object(
            self.module.http.client,
            "HTTPConnection",
            side_effect=[first_connection, second_connection],
        ) as connection:
            self.controller.health_check(18081)
        self.assertEqual(connection.call_args_list, [call("127.0.0.2", 18081, timeout=3)] * 2)
        first_connection.putheader.assert_called_once_with("Host", "example.test")

    def test_current_and_list_are_read_only_and_do_not_lock(self) -> None:
        release_id = self.create_release(1)
        self.link("current", release_id)
        output = io.StringIO()
        with patch.object(self.module.fcntl, "flock") as flock:
            self.controller.execute("current", None, output)
        self.assertEqual(output.getvalue(), f"{release_id}\n")
        flock.assert_not_called()


class StaticSiteAnsibleContractTests(unittest.TestCase):
    def test_rendered_systemd_unit_verifies(self) -> None:
        source = (ROLE_ROOT / "templates/static-site-release.service.j2").read_text()
        replacements = {
            "{{ operation | capitalize }}": "Deploy",
            "{{ operation }}": "deploy",
            "{{ static_site_name }}": "example",
            "{{ static_site_controller_path }}": "/bin/true",
            "{{ static_site_controller_config_path }}": "/tmp/example.json",
            "{{ static_site_root }}": "/tmp/example",
        }
        for expression, value in replacements.items():
            source = source.replace(expression, value)
        self.assertNotIn("{{", source)
        with tempfile.TemporaryDirectory() as temporary:
            unit = Path(temporary) / "static-site-deploy-example@.service"
            unit.write_text(source, encoding="utf-8")
            nginx = Path(temporary) / "nginx.service"
            nginx.write_text(
                "[Service]\nType=oneshot\nExecStart=/bin/true\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["systemd-analyze", "verify", str(nginx), str(unit)],
                check=False,
                capture_output=True,
                text=True,
            )
        if result.returncode != 0 and "Operation not permitted" in result.stderr:
            self.skipTest("systemd-analyze is restricted by the test sandbox")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sysupdate_definition_uses_signed_local_feed(self) -> None:
        template = (ROLE_ROOT / "templates/static-site.transfer.conf.j2").read_text()
        self.assertIn("Type=url-tar", template)
        self.assertIn("Path=http://127.0.0.1:", template)
        self.assertIn("MatchPattern={{ static_site_name }}-@v.tar.gz", template)
        self.assertIn("MatchPattern=releases/@v", template)
        self.assertIn("CurrentSymlink=staged", template)
        self.assertIn("Verify=yes", template)
        self.assertIn("static_site_release_retention | int + 1", template)

    def test_units_polkit_config_and_nginx_are_per_site(self) -> None:
        tasks = (ROLE_ROOT / "tasks/main.yml").read_text()
        unit = (ROLE_ROOT / "templates/static-site-release.service.j2").read_text()
        polkit = (ROLE_ROOT / "templates/polkit.rules.j2").read_text()
        nginx = (ROLE_ROOT / "templates/nginx.conf.j2").read_text()
        config = (ROLE_ROOT / "templates/controller.json.j2").read_text()
        for obsolete in (
            "manifest_schema_version",
            "archive_max_members",
            "archive_max_expanded_size",
            "static_site_script_file_name",
            "NOPASSWD",
        ):
            self.assertNotIn(obsolete, tasks)
        self.assertIn("ExecStart={{ static_site_controller_path }}", unit)
        self.assertIn("{{ operation }} %i", unit)
        self.assertIn('verb === "start"', polkit)
        self.assertIn("deployPrefix", polkit)
        self.assertIn("rollbackPrefix", polkit)
        self.assertIn("[0-9a-f]{12}", polkit)
        self.assertEqual(nginx.count("listen 127.0.0.1:"), 2)
        self.assertIn("/incoming", nginx)
        self.assertIn("/staged", nginx)
        self.assertIn("/current", nginx)
        self.assertIn('"definitions_path"', config)
        self.assertIn("systemd-container", tasks)
        self.assertIn("import-pubring.gpg", (ROLE_ROOT / "handlers/main.yml").read_text())

    def test_two_instances_have_independent_paths_ports_and_units(self) -> None:
        defaults = (ROLE_ROOT / "defaults/main.yml").read_text()
        self.assertIn('static_site_root: "/srv/www/{{ static_site_name }}"', defaults)
        self.assertIn("static_site_feed_port", defaults)
        self.assertIn("static_site_staging_health_port", defaults)
        tasks = (ROLE_ROOT / "tasks/main.yml").read_text()
        self.assertIn("sysupdate.{{ static_site_name }}.d", defaults)
        self.assertIn("-{{ static_site_name }}@.service", tasks)


if __name__ == "__main__":
    unittest.main()
