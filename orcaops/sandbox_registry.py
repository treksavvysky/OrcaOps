#!/usr/bin/env python3
"""
Sandbox Registry - Tracks generated sandbox projects
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

from orcaops import logger

# Default registry location
DEFAULT_REGISTRY_DIR = Path.home() / ".orcaops"
DEFAULT_REGISTRY_FILE = DEFAULT_REGISTRY_DIR / "sandboxes.json"


@dataclass
class SandboxEntry:
    """Represents a registered sandbox"""
    name: str
    template: str
    path: str
    created_at: str
    status: str = "stopped"  # stopped, running, unknown

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "SandboxEntry":
        return cls(**data)


class SandboxRegistry:
    """Manages the registry of generated sandboxes"""

    def __init__(self, registry_file: Path = DEFAULT_REGISTRY_FILE):
        self.registry_file = registry_file
        self._ensure_registry_dir()
        self._sandboxes: Dict[str, SandboxEntry] = {}
        self._load()

    def _ensure_registry_dir(self):
        """Ensure the registry directory exists"""
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)

    def _load(self):
        """Load the registry from disk"""
        if self.registry_file.exists():
            try:
                with open(self.registry_file, 'r') as f:
                    data = json.load(f)
                    self._sandboxes = {
                        name: SandboxEntry.from_dict(entry)
                        for name, entry in data.get("sandboxes", {}).items()
                    }
                logger.debug(f"Loaded {len(self._sandboxes)} sandboxes from registry")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load registry, starting fresh: {e}")
                self._sandboxes = {}
        else:
            self._sandboxes = {}

    def _save(self):
        """Save the registry to disk"""
        data = {
            "version": "1.0",
            "sandboxes": {name: entry.to_dict() for name, entry in self._sandboxes.items()}
        }
        with open(self.registry_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Saved {len(self._sandboxes)} sandboxes to registry")

    def register(self, name: str, template: str, path: str) -> SandboxEntry:
        """Register a new sandbox"""
        entry = SandboxEntry(
            name=name,
            template=template,
            path=os.path.abspath(path),
            created_at=datetime.now().isoformat(),
            status="stopped"
        )
        self._sandboxes[name] = entry
        self._save()
        logger.info(f"Registered sandbox '{name}' at {path}")
        return entry

    def unregister(self, name: str) -> bool:
        """Remove a sandbox from the registry"""
        if name in self._sandboxes:
            del self._sandboxes[name]
            self._save()
            logger.info(f"Unregistered sandbox '{name}'")
            return True
        return False

    def get(self, name: str) -> Optional[SandboxEntry]:
        """Get a sandbox by name"""
        return self._sandboxes.get(name)

    def list_all(self) -> List[SandboxEntry]:
        """List all registered sandboxes"""
        return list(self._sandboxes.values())

    def update_status(self, name: str, status: str) -> bool:
        """Update the status of a sandbox"""
        if name in self._sandboxes:
            self._sandboxes[name].status = status
            self._save()
            return True
        return False

    def exists(self, name: str) -> bool:
        """Check if a sandbox is registered"""
        return name in self._sandboxes

    def path_exists(self, path: str) -> bool:
        """Check if a path is already registered"""
        abs_path = os.path.abspath(path)
        return any(entry.path == abs_path for entry in self._sandboxes.values())

    def validate_sandbox(self, name: str) -> Dict[str, bool]:
        """Validate that a sandbox's files still exist"""
        entry = self.get(name)
        if not entry:
            return {"exists": False, "has_compose": False, "has_env": False}

        sandbox_path = Path(entry.path)
        return {
            "exists": sandbox_path.exists(),
            "has_compose": (sandbox_path / "docker-compose.yml").exists(),
            "has_env": (sandbox_path / ".env").exists(),
        }

    def cleanup_invalid(self) -> List[str]:
        """Remove sandboxes whose directories no longer exist"""
        removed = []
        for name in list(self._sandboxes.keys()):
            validation = self.validate_sandbox(name)
            if not validation["exists"]:
                self.unregister(name)
                removed.append(name)
        return removed


# Global registry instance
_registry: Optional[SandboxRegistry] = None


def get_registry() -> SandboxRegistry:
    """Get the global registry instance"""
    global _registry
    if _registry is None:
        _registry = SandboxRegistry()
    return _registry
