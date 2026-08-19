from pantheon_systems_cli.ansible.inventory import (
    get_all_hosts,
    InventoryError,
    InventoryName,
)


def complete_host(incomplete: str, inventory: InventoryName) -> list[str]:
    """
    Complete canonical machine names from the selected inventory
    for use in autocompletion.
    """

    try:
        hosts = get_all_hosts(inventory)
    except InventoryError:
        return []

    return [host for host in hosts if host.startswith(incomplete)]


def complete_local_host(incomplete: str) -> list[str]:
    """
    Complete canonical machine names from the "local" inventory
    for use in autocompletion.
    """
    return complete_host(incomplete, "local")


def complete_prod_host(incomplete: str) -> list[str]:
    """
    Complete canonical machine names from the "prod" inventory
    for use in autocompletion.
    """
    return complete_host(incomplete, "prod")
