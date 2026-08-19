# ai_generated

import unittest
from unittest.mock import patch

from pantheon_systems_cli.ansible.host import get_host_variables
from pantheon_systems_cli.ansible.inventory import (
    InventoryError,
    get_hosts_from_inventory,
    get_inventory_host_variables,
)


class InventoryHostVariablesTests(unittest.TestCase):
    def test_returns_validated_host_variable_mapping(self) -> None:
        inventory = {
            "_meta": {
                "hostvars": {
                    "beta-local": {"vm_ip": "192.0.2.2"},
                    "alpha-local": {"vm_ip": "192.0.2.1"},
                }
            }
        }

        with patch(
            "pantheon_systems_cli.ansible.inventory._load_inventory",
            return_value=inventory,
        ):
            host_variables = get_inventory_host_variables("local")
            hosts = get_hosts_from_inventory("local")
            variables = get_host_variables("alpha-local", "local")

        self.assertEqual(host_variables, inventory["_meta"]["hostvars"])
        self.assertEqual(hosts, ["alpha-local", "beta-local"])
        self.assertEqual(variables, {"vm_ip": "192.0.2.1"})

    def test_rejects_invalid_variables_for_any_host(self) -> None:
        inventory = {"_meta": {"hostvars": {"alpha-local": None}}}

        with patch(
            "pantheon_systems_cli.ansible.inventory._load_inventory",
            return_value=inventory,
        ):
            with self.assertRaisesRegex(InventoryError, "alpha-local"):
                get_inventory_host_variables("local")


if __name__ == "__main__":
    unittest.main()
