"""
Workflow execution engine.

Executes a workflow DAG level-by-level using threads for parallelism.
Individual jobs are submitted through JobManager.
"""

import logging
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, List, Optional

from orcaops.job_manager import JobManager
from orcaops.schemas import (
    JobSpec, SandboxSpec, JobCommand, JobStatus,
    WorkflowSpec, WorkflowJob, WorkflowRecord, WorkflowStatus,
    WorkflowJobStatus,
)
from orcaops.workflow_schema import (
    get_execution_order, expand_matrix, matrix_key,
    ConditionEvaluator,
)

logger = logging.getLogger("orcaops")

_TERMINAL_JOB_STATUSES = {
    JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.TIMED_OUT, JobStatus.CANCELLED,
}


class WorkflowRunner:
    """Executes a workflow DAG, delegating individual jobs to JobManager."""

    def __init__(self, job_manager: JobManager, max_parallel: int = 4):
        self.jm = job_manager
        self.max_parallel = max_parallel

    def run(
        self,
        spec: WorkflowSpec,
        workflow_id: str,
        cancel_event: threading.Event,
        triggered_by: Optional[str] = None,
    ) -> WorkflowRecord:
        """
        Execute the workflow synchronously (called in a background thread).
        Returns the final WorkflowRecord.
        """
        record = WorkflowRecord(
            workflow_id=workflow_id,
            spec_name=spec.name,
            status=WorkflowStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            env=dict(spec.env),
            triggered_by=triggered_by,
        )

        # Initialize job statuses as QUEUED
        for job_name in spec.jobs:
            record.job_statuses[job_name] = WorkflowJobStatus(
                job_name=job_name,
                status=JobStatus.QUEUED,
            )

        levels = get_execution_order(spec)

        try:
            for level_idx, level in enumerate(levels):
                if cancel_event.is_set():
                    record.status = WorkflowStatus.CANCELLED
                    record.error = "Workflow cancelled by user."
                    # Mark remaining queued jobs as cancelled
                    for jn in level:
                        if record.job_statuses[jn].status == JobStatus.QUEUED:
                            record.job_statuses[jn].status = JobStatus.CANCELLED
                            record.job_statuses[jn].error = "Workflow cancelled"
                    for remaining in levels[level_idx + 1:]:
                        for jn in remaining:
                            if record.job_statuses[jn].status == JobStatus.QUEUED:
                                record.job_statuses[jn].status = JobStatus.CANCELLED
                                record.job_statuses[jn].error = "Workflow cancelled"
                    break

                # Filter jobs by conditions and on_complete rules
                jobs_to_run = []
                for job_name in level:
                    job_def = spec.jobs[job_name]
                    if self._should_run_job(job_def, record):
                        jobs_to_run.append(job_name)
                    else:
                        record.job_statuses[job_name].status = JobStatus.CANCELLED
                        record.job_statuses[job_name].error = "Skipped: condition not met"

                if not jobs_to_run:
                    continue

                # Run jobs in this level in parallel
                self._run_level(spec, jobs_to_run, record, workflow_id, cancel_event)

                # Check if any non-"always" job failure should halt the workflow
                has_failure = any(
                    record.job_statuses[jn].status in {JobStatus.FAILED, JobStatus.TIMED_OUT}
                    for jn in jobs_to_run
                    if spec.jobs[jn].on_complete == "success"
                )
                if has_failure:
                    # Cancel remaining downstream jobs that require success
                    # but keep "always" and "failure" jobs eligible
                    has_remaining = False
                    for remaining in levels[level_idx + 1:]:
                        for jn in remaining:
                            if record.job_statuses[jn].status == JobStatus.QUEUED:
                                job_on_complete = spec.jobs[jn].on_complete
                                if job_on_complete == "success":
                                    record.job_statuses[jn].status = JobStatus.CANCELLED
                                    record.job_statuses[jn].error = "Skipped: upstream failure"
                                else:
                                    has_remaining = True
                    if not has_remaining:
                        break

        except Exception as e:
            logger.error(f"Workflow {workflow_id} failed: {e}", exc_info=True)
            record.error = str(e)

        # Determine final status
        record.finished_at = datetime.now(timezone.utc)
        record.status = self._compute_final_status(record)
        return record

    def _should_run_job(self, job_def: WorkflowJob, record: WorkflowRecord) -> bool:
        """Check if a job should run based on conditions and on_complete."""
        if job_def.on_complete == "always":
            pass  # Always run, but still check if_condition
        elif job_def.on_complete == "failure":
            # Only run if at least one required job failed
            has_failure = any(
                record.job_statuses[dep].status in {JobStatus.FAILED, JobStatus.TIMED_OUT}
                for dep in job_def.requires
                if dep in record.job_statuses
            )
            if not has_failure:
                return False
        else:
            # "success" (default): all requires must have succeeded
            all_success = all(
                record.job_statuses[dep].status == JobStatus.SUCCESS
                for dep in job_def.requires
                if dep in record.job_statuses
            )
            if not all_success:
                return False

        # Evaluate if_condition
        if job_def.if_condition:
            job_status_map = {
                name: js.status.value
                for name, js in record.job_statuses.items()
            }
            evaluator = ConditionEvaluator(job_status_map, record.env)
            if not evaluator.evaluate(job_def.if_condition):
                return False

        return True

    def _run_level(
        self,
        spec: WorkflowSpec,
        job_names: List[str],
        record: WorkflowRecord,
        workflow_id: str,
        cancel_event: threading.Event,
    ) -> None:
        """Run all jobs in a level in parallel using ThreadPoolExecutor."""
        # Expand matrix jobs into individual tasks
        tasks: List[tuple] = []  # (job_name, matrix_params_or_None)
        for job_name in job_names:
            job_def = spec.jobs[job_name]
            if job_def.matrix:
                variants = expand_matrix(job_def.matrix)
                for params in variants:
                    tasks.append((job_name, params))
            else:
                tasks.append((job_name, None))

        with ThreadPoolExecutor(max_workers=min(self.max_parallel, len(tasks))) as pool:
            futures = {}
            for job_name, params in tasks:
                job_def = spec.jobs[job_name]
                future = pool.submit(
                    self._execute_single_job,
                    spec, job_def, record, workflow_id, cancel_event, params,
                )
                futures[future] = (job_name, params)

            for future in as_completed(futures):
                job_name, params = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Job {job_name} raised exception: {e}")

    def _execute_single_job(
        self,
        spec: WorkflowSpec,
        job_def: WorkflowJob,
        record: WorkflowRecord,
        workflow_id: str,
        cancel_event: threading.Event,
        matrix_params: Optional[Dict[str, str]] = None,
    ) -> None:
        """Submit a single job to JobManager, poll until completion."""
        job_name = job_def.name
        mk = matrix_key(matrix_params) if matrix_params else None

        # Generate unique job_id
        suffix = f"-{mk.replace(',', '-').replace('=', '')}" if mk else ""
        job_id = f"wf-{workflow_id}-{job_name}{suffix}"
        job_id = re.sub(r'[^a-zA-Z0-9_\-]', '-', job_id)[:128]

        # Merge environment: workflow env -> job env -> matrix params
        merged_env = dict(spec.env)
        merged_env.update(job_def.env)
        if matrix_params:
            for k, v in matrix_params.items():
                merged_env[f"MATRIX_{k.upper()}"] = v

        # Interpolate ${{ matrix.xxx }} in image name
        image = job_def.image
        if matrix_params:
            for k, v in matrix_params.items():
                image = image.replace(f"${{{{ matrix.{k} }}}}", v)

        # Start service containers if defined
        network_name = None
        service_container_ids: Dict[str, str] = {}
        svc_mgr = None

        if job_def.services:
            try:
                from orcaops.service_manager import ServiceManager
                svc_mgr = ServiceManager()
                network_name = f"orcaops-{workflow_id}-{job_name}"
                service_container_ids, svc_env = svc_mgr.start_services(
                    job_def.services, network_name, workflow_id,
                )
                merged_env.update(svc_env)
            except Exception as e:
                logger.error(f"Failed to start services for {job_name}: {e}")
                status_entry = record.job_statuses[job_name]
                status_entry.status = JobStatus.FAILED
                status_entry.error = f"Service startup failed: {e}"
                status_entry.finished_at = datetime.now(timezone.utc)
                return

        try:
            # Build JobSpec
            commands = [
                JobCommand(command=cmd, timeout_seconds=job_def.timeout)
                for cmd in job_def.commands
            ]

            job_spec = JobSpec(
                job_id=job_id,
                sandbox=SandboxSpec(
                    image=image,
                    env=merged_env,
                    network_name=network_name,
                ),
                commands=commands,
                artifacts=list(job_def.artifacts),
                ttl_seconds=max(job_def.timeout, 10),
                triggered_by="workflow",
                parent_job_id=workflow_id,
                tags=["workflow", spec.name, job_name],
            )

            # Update record
            status_entry = record.job_statuses[job_name]
            status_entry.job_id = job_id
            status_entry.status = JobStatus.RUNNING
            status_entry.started_at = datetime.now(timezone.utc)
            if mk:
                status_entry.matrix_key = mk

            try:
                self.jm.submit_job(job_spec)
            except ValueError as e:
                status_entry.status = JobStatus.FAILED
                status_entry.error = str(e)
                status_entry.finished_at = datetime.now(timezone.utc)
                return

            # Poll for completion
            deadline = time.time() + job_def.timeout + 30
            while time.time() < deadline:
                if cancel_event.is_set():
                    self.jm.cancel_job(job_id)
                    status_entry.status = JobStatus.CANCELLED
                    status_entry.error = "Workflow cancelled"
                    status_entry.finished_at = datetime.now(timezone.utc)
                    return
                run_record = self.jm.get_job(job_id)
                if run_record and run_record.status in _TERMINAL_JOB_STATUSES:
                    status_entry.status = run_record.status
                    status_entry.finished_at = run_record.finished_at
                    if run_record.error:
                        status_entry.error = run_record.error
                    return
                time.sleep(0.5)

            # Timed out waiting
            self.jm.cancel_job(job_id)
            status_entry.status = JobStatus.TIMED_OUT
            status_entry.error = f"Job did not complete within {job_def.timeout}s"
            status_entry.finished_at = datetime.now(timezone.utc)
        finally:
            # Cleanup service containers
            if svc_mgr and service_container_ids:
                try:
                    svc_mgr.stop_services(service_container_ids, network_name)
                except Exception as e:
                    logger.warning(f"Failed to cleanup services for {job_name}: {e}")

    def _compute_final_status(self, record: WorkflowRecord) -> WorkflowStatus:
        """Determine overall workflow status from individual job statuses."""
        statuses = {js.status for js in record.job_statuses.values()}

        if all(s == JobStatus.SUCCESS for s in statuses):
            return WorkflowStatus.SUCCESS
        if all(s == JobStatus.CANCELLED for s in statuses):
            return WorkflowStatus.CANCELLED
        if any(s == JobStatus.CANCELLED for s in statuses) and not any(
            s in {JobStatus.FAILED, JobStatus.TIMED_OUT} for s in statuses
        ):
            return WorkflowStatus.CANCELLED
        if any(s == JobStatus.SUCCESS for s in statuses) and any(
            s in {JobStatus.FAILED, JobStatus.TIMED_OUT, JobStatus.CANCELLED} for s in statuses
        ):
            return WorkflowStatus.PARTIAL
        return WorkflowStatus.FAILED
