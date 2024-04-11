import yaml
from pathlib import Path

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
KFAM_IMAGE = METADATA["resources"]["kfam-image"]["upstream-source"]
PROFILE_IMAGE = METADATA["resources"]["profile-image"]["upstream-source"]
ADMISSION_WEBHOOK = "admission-webhook"
ADMISSION_WEBHOOK_CHANNEL = "1.8/stable"
ADMISSION_WEBHOOK_TRUST = True
