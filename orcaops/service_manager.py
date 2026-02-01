"""
Service container lifecycle management for workflow jobs.

Handles starting service containers (postgres, redis, etc.) with health checks,
injecting service hostnames into job environment, and cleanup.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

from orcaops.docker_manager import DockerManager
from orcaops.schemas import ServiceDefinition

logger = logging.getLogger("orcaops")


class ServiceManager:
    """Manages service containers for a workflow job."""

    def __init__(self, docker_manager: Optional[DockerManager] = None):
        self.dm = docker_manager or DockerManager()

    def start_services(
        self,
        services: Dict[str, ServiceDefinition],
        network_name: str,
        workflow_id: str,
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        """
        Start all service containers and wait for health checks.

        Returns:
            (container_ids: {service_name: container_id},
             env_vars: {SERVICE_HOST: hostname, SERVICE_PORT: port})
        """
        container_ids: Dict[str, str] = {}
        env_vars: Dict[str, str] = {}

        # Create network for this workflow context
        network_id = self.dm.create_network(
            network_name,
            labels={"orcaops.workflow_id": workflow_id},
        )

        for svc_name, svc_def in services.items():
            hostname = f"{workflow_id}-{svc_name}"
            try:
                container_id = self.dm.run(
                    svc_def.image,
                    detach=True,
                    environment=svc_def.env,
                    labels={
                        "orcaops.workflow_id": workflow_id,
                        "orcaops.service": svc_name,
                    },
                    name=hostname,
                )
                container_ids[svc_name] = container_id

                # Connect to network with alias
                self.dm.connect_to_network(
                    container_id, network_id, aliases=[svc_name, hostname]
                )

                # Inject env vars
                upper_name = svc_name.upper().replace("-", "_")
                env_vars[f"{upper_name}_HOST"] = svc_name
                default_port = _infer_default_port(svc_def.image)
                if default_port:
                    env_vars[f"{upper_name}_PORT"] = str(default_port)

            except Exception as e:
                logger.error(f"Failed to start service {svc_name}: {e}")
                self.stop_services(container_ids, network_name)
                raise

        # Wait for health checks
        for svc_name, svc_def in services.items():
            if svc_def.health_check and svc_name in container_ids:
                self._wait_for_health(
                    container_ids[svc_name], svc_def.health_check, svc_name
                )

        return container_ids, env_vars

    def stop_services(
        self,
        container_ids: Dict[str, str],
        network_name: str,
    ) -> None:
        """Stop and remove all service containers, then remove the network."""
        for svc_name, cid in container_ids.items():
            try:
                self.dm.rm(cid, force=True)
            except Exception as e:
                logger.warning(f"Failed to remove service {svc_name}: {e}")

        try:
            self.dm.remove_network(network_name)
        except Exception as e:
            logger.warning(f"Failed to remove network {network_name}: {e}")

    def _wait_for_health(
        self,
        container_id: str,
        health_check: Dict,
        service_name: str,
    ) -> None:
        """Poll container health until healthy or timeout."""
        interval = _parse_duration(health_check.get("interval", "5s"))
        timeout = _parse_duration(health_check.get("timeout", "30s"))
        retries = health_check.get("retries", 5)

        deadline = time.time() + timeout
        attempts = 0

        while time.time() < deadline and attempts < retries:
            try:
                container = self.dm.client.containers.get(container_id)
                health = container.attrs.get("State", {}).get("Health", {})
                status = health.get("Status", "none")
                if status == "healthy":
                    logger.info(f"Service {service_name} is healthy.")
                    return
                if status == "none" and container.status == "running":
                    logger.info(f"Service {service_name} is running (no healthcheck).")
                    return
            except Exception as e:
                logger.warning(f"Health check poll for {service_name}: {e}")

            attempts += 1
            time.sleep(interval)

        logger.warning(f"Service {service_name} health check timed out after {timeout}s")


def _infer_default_port(image: str) -> Optional[int]:
    """Infer default port from well-known Docker images."""
    image_lower = image.lower().split(":")[0].split("/")[-1]
    defaults = {
        "postgres": 5432,
        "mysql": 3306,
        "mariadb": 3306,
        "redis": 6379,
        "mongo": 27017,
        "mongodb": 27017,
        "rabbitmq": 5672,
        "elasticsearch": 9200,
        "memcached": 11211,
        "nginx": 80,
    }
    return defaults.get(image_lower)


def _parse_duration(s: str) -> float:
    """Parse duration string like '5s', '100ms' to seconds."""
    s = s.strip().lower()
    if s.endswith("ms"):
        return float(s[:-2]) / 1000
    if s.endswith("s"):
        return float(s[:-1])
    if s.endswith("m"):
        return float(s[:-1]) * 60
    return float(s)
