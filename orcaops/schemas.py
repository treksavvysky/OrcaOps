from pydantic import BaseModel
from typing import List, Dict, Optional

class Container(BaseModel):
    """Schema for a Docker container."""
    id: str
    names: List[str]
    image: str
    status: str

class ContainerInspect(BaseModel):
    """Schema for detailed container inspection."""
    id: str
    name: str
    image: str
    state: Dict
    network_settings: Dict

class CleanupReport(BaseModel):
    """Schema for the result of a cleanup operation."""
    stopped_containers: List[str]
    removed_containers: List[str]
    errors: List[str]

class Template(BaseModel):
    """Schema for a sandbox template."""
    name: str
    description: str
    category: str
    services: Dict

class TemplateList(BaseModel):
    """Schema for a list of sandbox templates."""
    templates: Dict[str, Template]
