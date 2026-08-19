from pantheon_systems_cli.types import JsonValue
from pantheon_systems_cli.ansible.inventory import (
    InventoryName,
    InventoryError,
    get_inventory_host_variables,
)


def get_host_variables(host: str, inventory: InventoryName) -> dict[str, JsonValue]:
    """Return the resolved Ansible variables for one canonical host name."""

    hostvars = get_inventory_host_variables(inventory)
    variables = hostvars.get(host)

    if variables is None:
        raise InventoryError(f"Host {host!r} is not in the {inventory!r} inventory")

    return variables
