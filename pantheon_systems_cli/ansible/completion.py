from pantheon_systems_cli.ansible.inventory import (
    get_hosts as get_inventory_hosts,
    InventoryError,
)


def local_host(incomplete: str) -> list[str]:
    """
    Complete canonical machine names from the local inventory
    for use in autocompletion.
    """

    try:
        hosts = get_inventory_hosts("local")
    except InventoryError:
        return []

    return [host for host in hosts if host.startswith(incomplete)]
