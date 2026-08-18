# ai_generated

import unittest
from typing import Any
from unittest.mock import Mock, call, patch

import libvirt  # pyright: ignore[reportMissingTypeStubs]
import typer
from typer.testing import CliRunner

from pantheon_systems_cli.ansible import InventoryError
from pantheon_systems_cli.cli import app


HOST_VARIABLES = {
    "vm_network": "default",
    "vm_mac": "52:54:00:00:00:10",
    "vm_ip": "192.168.122.10",
}


class FakeDomain:
    def __init__(self, active: bool = False) -> None:
        self.active = active

    def isActive(self) -> bool:
        return self.active


class VmCliTests(unittest.TestCase):
    runner = CliRunner()

    def invoke(self, *args: str, input: str | None = None) -> Any:
        return self.runner.invoke(app, ["vm", *args], input=input)

    def inventory_patch(
        self,
        hosts: dict[str, dict[str, object]] | None = None,
    ) -> Any:
        return patch(
            "pantheon_systems_cli.vm.cli.get_inventory_host_variables",
            return_value=hosts
            or {
                "beta-local": HOST_VARIABLES,
                "alpha-local": HOST_VARIABLES,
            },
        )

    def test_requires_exactly_one_selector(self) -> None:
        for args in (("state",), ("state", "alpha-local", "--all")):
            with self.subTest(args=args):
                result = self.invoke(*args)

                self.assertEqual(result.exit_code, 2)
                self.assertIn("Specify exactly one of HOST or --all", result.output)

    def test_unknown_host_and_empty_inventory_fail(self) -> None:
        with self.inventory_patch():
            unknown = self.invoke("state", "missing-local")

        with patch(
            "pantheon_systems_cli.vm.cli.get_inventory_host_variables",
            return_value={},
        ):
            empty = self.invoke("state", "--all")

        self.assertEqual(unknown.exit_code, 1)
        self.assertIn("not in the 'local' inventory", unknown.output)
        self.assertEqual(empty.exit_code, 1)
        self.assertIn("does not contain any hosts", empty.output)

    def test_inventory_loading_failure_is_reported(self) -> None:
        with patch(
            "pantheon_systems_cli.vm.cli.get_inventory_host_variables",
            side_effect=InventoryError("inventory unavailable"),
        ):
            result = self.invoke("state", "--all")

        self.assertEqual(result.exit_code, 1)
        self.assertIn("inventory unavailable", result.output)

    def test_all_script_commands_continue_in_sorted_order_then_fail(self) -> None:
        calls: list[str] = []

        def run_script(filename: str, args: tuple[str, ...]) -> None:
            self.assertEqual(filename, "set_up_vm.sh")
            calls.append(args[0])
            if args[0] == "alpha-local":
                raise typer.Exit(7)

        with self.inventory_patch(), patch(
            "pantheon_systems_cli.vm.cli.run_privileged_script",
            side_effect=run_script,
        ):
            result = self.invoke("create", "--all")

        self.assertEqual(calls, ["alpha-local", "beta-local"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Operation failed for 1 VM(s): alpha-local", result.output)

    def test_single_script_command_preserves_exit_code(self) -> None:
        with self.inventory_patch(), patch(
            "pantheon_systems_cli.vm.cli.run_privileged_script",
            side_effect=typer.Exit(7),
        ):
            result = self.invoke("create", "alpha-local")

        self.assertEqual(result.exit_code, 7)

    def test_all_libvirt_commands_share_connection_and_use_sorted_order(self) -> None:
        domains = {
            "alpha-local": FakeDomain(active=True),
            "beta-local": FakeDomain(active=False),
        }
        connection = Mock()

        def lookup_domain(host: str) -> FakeDomain:
            return domains[host]

        connection.lookupByName.side_effect = lookup_domain

        with self.inventory_patch() as load_inventory, patch(
            "pantheon_systems_cli.vm.cli.libvirt.open",
            return_value=connection,
        ) as open_connection:
            result = self.invoke("state", "--all")

        self.assertEqual(result.exit_code, 0)
        load_inventory.assert_called_once_with("local")
        open_connection.assert_called_once_with("qemu:///system")
        self.assertEqual(
            connection.lookupByName.call_args_list,
            [call("alpha-local"), call("beta-local")],
        )
        connection.close.assert_called_once_with()

    def test_all_libvirt_commands_continue_after_operation_failure(self) -> None:
        first = Mock()
        first.isActive.side_effect = libvirt.libvirtError("state failed")
        second = FakeDomain(active=True)
        connection = Mock()
        connection.lookupByName.side_effect = [first, second]

        with self.inventory_patch(), patch(
            "pantheon_systems_cli.vm.cli.libvirt.open",
            return_value=connection,
        ):
            result = self.invoke("state", "--all")

        self.assertEqual(connection.lookupByName.call_count, 2)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Could not get state of alpha-local", result.output)
        self.assertIn("Operation failed for 1 VM(s): alpha-local", result.output)

    def test_each_libvirt_command_accepts_host_and_all_selectors(self) -> None:
        for command in ("start", "restart", "shutdown", "state"):
            for selector in (("alpha-local",), ("--all",)):
                with self.subTest(command=command, selector=selector):
                    domain = Mock()
                    domain.isActive.return_value = True
                    connection = Mock()
                    connection.lookupByName.return_value = domain

                    with self.inventory_patch(), patch(
                        "pantheon_systems_cli.vm.cli.libvirt.open",
                        return_value=connection,
                    ):
                        result = self.invoke(command, *selector)

                    self.assertEqual(result.exit_code, 0, result.output)
                    connection.close.assert_called_once_with()

    def test_shutdown_all_accepts_force_option(self) -> None:
        domain = Mock()
        domain.isActive.return_value = True
        connection = Mock()
        connection.lookupByName.return_value = domain

        with self.inventory_patch(), patch(
            "pantheon_systems_cli.vm.cli.libvirt.open",
            return_value=connection,
        ):
            result = self.invoke("shutdown", "--all", "--force")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(domain.destroy.call_count, 2)

    def test_destroy_all_cancellation_runs_no_scripts(self) -> None:
        with self.inventory_patch(), patch(
            "pantheon_systems_cli.vm.cli.run_privileged_script"
        ) as run_script:
            result = self.invoke("destroy", "--all", input="n\n")

        self.assertEqual(result.exit_code, 0)
        self.assertIn("alpha-local", result.output)
        self.assertIn("beta-local", result.output)
        self.assertIn("Cancelled", result.output)
        run_script.assert_not_called()

    def test_destroy_all_confirms_once_and_skips_script_prompts(self) -> None:
        with self.inventory_patch(), patch(
            "pantheon_systems_cli.vm.cli.run_privileged_script"
        ) as run_script:
            result = self.invoke("destroy", "--all", input="y\n")

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(
            run_script.call_args_list,
            [
                call("destroy_vm.sh", ("--yes", "alpha-local")),
                call("destroy_vm.sh", ("--yes", "beta-local")),
            ],
        )

    def test_single_destroy_retains_script_confirmation(self) -> None:
        with self.inventory_patch(), patch(
            "pantheon_systems_cli.vm.cli.run_privileged_script"
        ) as run_script:
            result = self.invoke("destroy", "alpha-local")

        self.assertEqual(result.exit_code, 0)
        run_script.assert_called_once_with("destroy_vm.sh", ("alpha-local",))


if __name__ == "__main__":
    unittest.main()
