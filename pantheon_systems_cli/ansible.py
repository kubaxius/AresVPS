import json
import subprocess
from typing import Literal, TypeAlias, cast

from pantheon_systems_cli.config import ANSIBLE_INVENTORIES_PATH

# It uses TypeAlias explicitly because it is recursive.
JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)

type InventoryName = Literal["local", "prod"]


class InventoryError(RuntimeError):
    """Raised when an Ansible inventory cannot be loaded."""


def _load_inventory(inventory: InventoryName) -> dict[str, JsonValue]:
    inventory_path = ANSIBLE_INVENTORIES_PATH / inventory

    if not inventory_path.is_dir():
        raise InventoryError(f"Ansible inventory does not exist: {inventory_path}")

    try:
        result = subprocess.run(
            [
                "ansible-inventory",
                "--inventory",
                str(inventory_path),
                "--list",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        inventory_data = cast(JsonValue, json.loads(result.stdout))
    except FileNotFoundError as error:
        raise InventoryError("ansible-inventory is not installed") from error
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or str(error)
        raise InventoryError(f"Could not load Ansible inventory: {message}") from error
    except json.JSONDecodeError as error:
        raise InventoryError("ansible-inventory returned invalid JSON") from error

    if not isinstance(inventory_data, dict):
        raise InventoryError("ansible-inventory returned an unexpected data structure")

    return inventory_data


def get_inventory_host_variables(
    inventory: InventoryName,
) -> dict[str, dict[str, JsonValue]]:
    """Return the resolved variables for every canonical inventory host."""

    inventory_data = _load_inventory(inventory)
    metadata = inventory_data.get("_meta")
    if not isinstance(metadata, dict):
        raise InventoryError("Ansible inventory does not contain host metadata")

    hostvars = metadata.get("hostvars")
    if not isinstance(hostvars, dict):
        raise InventoryError("Ansible inventory does not contain host variables")

    validated_hostvars: dict[str, dict[str, JsonValue]] = {}
    for host, variables in hostvars.items():
        if not isinstance(variables, dict):
            raise InventoryError(f"Ansible returned invalid variables for host {host!r}")
        validated_hostvars[host] = variables

    return validated_hostvars


def get_hosts_from_inventory(inventory: InventoryName) -> list[str]:
    """Return the canonical host names declared by an inventory."""

    return sorted(get_inventory_host_variables(inventory))


def get_host_variables(host: str, inventory: InventoryName) -> dict[str, JsonValue]:
    """Return the resolved Ansible variables for one canonical host name."""

    hostvars = get_inventory_host_variables(inventory)
    variables = hostvars.get(host)

    if variables is None:
        raise InventoryError(f"Host {host!r} is not in the {inventory!r} inventory")

    return variables
