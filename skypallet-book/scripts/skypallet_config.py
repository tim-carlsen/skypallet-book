# skypallet_config.py
import yaml
from pathlib import Path

def load_config(path="skypallet_config_mac.yml"):
    """
    Load YAML config and expand simple format placeholders.

    Returns a dict.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open() as f:
        cfg = yaml.safe_load(f)

    # expand simple {nas_root} etc in paths
    paths = cfg.get("paths", {})
    # first resolve nas_root
    nas_root = paths.get("nas_root")
    if nas_root is not None:
        nas_root = str(Path(nas_root))  # normalize separators
        paths["nas_root"] = nas_root

    # expand other paths that reference {nas_root} or each other
    expanded = {}
    for key, value in paths.items():
        if isinstance(value, str):
            expanded[key] = value.format(**paths)
        else:
            expanded[key] = value
    cfg["paths"] = expanded

    return cfg
