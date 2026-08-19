from pathlib import Path

PROJECT_PATH: Path = Path(__file__).resolve().parent.parent
SCRIPTS_PATH: Path = PROJECT_PATH / "scripts"
ANSIBLE_PATH: Path = PROJECT_PATH / "ansible"
ANSIBLE_INVENTORIES_PATH: Path = ANSIBLE_PATH / "inventories"
ANSIBLE_ROLES_PATH: Path = ANSIBLE_PATH / "roles"
LOCAL_INVENTORY_PATH: Path = ANSIBLE_INVENTORIES_PATH / "local"
PROD_INVENTORY_PATH: Path = ANSIBLE_INVENTORIES_PATH / "prod"
PLAYBOOK_PATH: Path = ANSIBLE_PATH / "site.yml"

IMAGE_URL: str = (
    "https://cloud-images.ubuntu.com"
    "/releases/noble/release/ubuntu-24.04-server-cloudimg-amd64.img"
)
IMAGE_HASH_URL: str = (
    "https://cloud-images.ubuntu.com/releases/noble/release/SHA256SUMS"
)

IMAGE_DIR: Path = PROJECT_PATH / "vm"

IMAGE_PATH: Path = IMAGE_DIR / "ubuntu-24.04-server-cloudimg-amd64.img"
HASH_PATH: Path = IMAGE_DIR / "SHA256SUMS"
