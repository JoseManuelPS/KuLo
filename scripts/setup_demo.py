#!/usr/bin/env python3
"""
Script to create test pods to test KuLo.

This script creates multiple pods with different log types (JSON, plain text, mixed)
to allow testing the KuLo application.

Usage:
    python scripts/setup_demo.py                    # Create pods in namespace 'demo'
    python scripts/setup_demo.py -n my-ns           # Create pods in custom namespace. Default namespace 'demo'.
    python scripts/setup_demo.py --timeout 300      # Create pods and wait 5 minutes before cleanup
    python scripts/setup_demo.py --cleanup          # Delete pods and namespace
    python scripts/setup_demo.py --cleanup --force  # Force delete (grace_period=0)
    python scripts/setup_demo.py --parallel 5       # Create pods in parallel
    python scripts/setup_demo.py --verify-logs      # Verify logs are being generated
    python scripts/setup_demo.py --show-status      # Show detailed pod status
    python scripts/setup_demo.py --use-deployments  # Create Deployments instead of Pods
"""

import asyncio
import argparse
import json
import logging
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from kubernetes_asyncio import client, config

# Configure logging
logger = logging.getLogger(__name__)
fmt = '%(levelname)-7s [%(asctime)s] %(message)s'
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(fmt, datefmt='%Y/%m/%d %H:%M:%S'))
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)
# Prevent duplicate logs by disabling propagation to root logger
logger.propagate = False

DEFAULT_NAMESPACE = "demo"
DEFAULT_IMAGE = "alpine:latest"
DEFAULT_PARALLEL = 3
DEFAULT_WAIT_TIMEOUT = 60


# ============================================================================
# Helper Functions for Building Kubernetes Resources
# ============================================================================

def create_resource_requirements(
    cpu_request: str = "100m",
    cpu_limit: str = "200m",
    memory_request: str = "64Mi",
    memory_limit: str = "128Mi"
) -> client.V1ResourceRequirements:
    """Create resource requirements for containers."""
    return client.V1ResourceRequirements(
        requests={
            "cpu": cpu_request,
            "memory": memory_request
        },
        limits={
            "cpu": cpu_limit,
            "memory": memory_limit
        }
    )


def create_security_context(
    run_as_non_root: bool = True,
    run_as_user: int = 1000,
    read_only_root_filesystem: bool = False,
    allow_privilege_escalation: bool = False
) -> client.V1SecurityContext:
    """Create security context for containers."""
    return client.V1SecurityContext(
        run_as_non_root=run_as_non_root,
        run_as_user=run_as_user if run_as_non_root else None,
        read_only_root_filesystem=read_only_root_filesystem,
        allow_privilege_escalation=allow_privilege_escalation,
        capabilities=client.V1Capabilities(
            drop=["ALL"]
        )
    )


def create_pod_metadata(
    name: str,
    namespace: str,
    labels: Dict[str, str],
    annotations: Optional[Dict[str, str]] = None
) -> client.V1ObjectMeta:
    """Create pod metadata with standard annotations."""
    if annotations is None:
        annotations = {}
    
    # Add standard annotations
    annotations.update({
        "kulo.dev/demo": "true",
        "kulo.dev/created-by": "setup_demo.py",
        "kulo.dev/created-at": datetime.utcnow().isoformat() + "Z"
    })
    
    return client.V1ObjectMeta(
        name=name,
        namespace=namespace,
        labels=labels,
        annotations=annotations
    )


def create_container(
    name: str,
    image: str,
    command: List[str],
    args: List[str],
    resources: Optional[client.V1ResourceRequirements] = None,
    security_context: Optional[client.V1SecurityContext] = None
) -> client.V1Container:
    """Create a container with standard configuration."""
    container = client.V1Container(
        name=name,
        image=image,
        command=command,
        args=args
    )
    
    if resources:
        container.resources = resources
    
    if security_context:
        container.security_context = security_context
    
    return container


# ============================================================================
# Namespace Management
# ============================================================================

async def ensure_namespace(
    api: client.CoreV1Api,
    namespace: str,
    labels: Optional[Dict[str, str]] = None,
    annotations: Optional[Dict[str, str]] = None
) -> None:
    """Create the namespace if it doesn't exist."""
    try:
        await api.read_namespace(name=namespace)
        logger.info(f"Namespace '{namespace}' already exists")
    except client.ApiException as e:
        if e.status == 404:
            logger.info(f"Creating namespace '{namespace}'...")
            metadata = client.V1ObjectMeta(
                name=namespace,
                labels=labels or {},
                annotations=annotations or {}
            )
            ns = client.V1Namespace(metadata=metadata)
            await api.create_namespace(body=ns)
            logger.info(f"Namespace '{namespace}' created successfully")
        else:
            raise




# ============================================================================
# Pod Status and Readiness Checks
# ============================================================================

async def wait_for_pod_running(
    api: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    check_containers: bool = True
) -> Tuple[bool, Optional[client.V1Pod]]:
    """Wait for a pod to be in Running state and containers ready.
    
    Returns:
        Tuple of (success: bool, pod: Optional[V1Pod])
    """
    logger.debug(f"Waiting for pod '{pod_name}' to be in Running state...")
    elapsed = 0
    last_pod = None
    
    while elapsed < timeout:
        try:
            pod = await api.read_namespaced_pod(name=pod_name, namespace=namespace)
            last_pod = pod
            phase = pod.status.phase
            
            if phase == "Running":
                # Check container status if requested
                if check_containers and pod.status.container_statuses:
                    all_running = True
                    for container_status in pod.status.container_statuses:
                        if not container_status.state or not container_status.state.running:
                            all_running = False
                            break
                        if not container_status.ready:
                            all_running = False
                            break
                    
                    if all_running:
                        logger.info(f"Pod '{pod_name}' is Running with all containers ready")
                        return True, pod
                else:
                    logger.info(f"Pod '{pod_name}' is in Running state")
                    return True, pod
                    
            elif phase == "Failed":
                reason = getattr(pod.status, 'reason', 'Unknown')
                message = getattr(pod.status, 'message', '')
                logger.error(f"Pod '{pod_name}' failed: {reason} - {message}")
                return False, pod
                
            elif phase == "Succeeded":
                logger.warning(f"Pod '{pod_name}' completed (Succeeded phase)")
                return False, pod
                
            # Check for CrashLoopBackOff
            if pod.status.container_statuses:
                for container_status in pod.status.container_statuses:
                    if container_status.state and container_status.state.waiting:
                        if container_status.state.waiting.reason == "CrashLoopBackOff":
                            logger.error(f"Pod '{pod_name}' container '{container_status.name}' in CrashLoopBackOff")
                            return False, pod
                            
        except client.ApiException as e:
            if e.status != 404:
                logger.warning(f"Error checking pod '{pod_name}' status: {e}")
        
        await asyncio.sleep(1)
        elapsed += 1
    
    logger.warning(f"Timeout waiting for pod '{pod_name}' to be Running")
    return False, last_pod


async def get_pod_status_summary(
    api: client.CoreV1Api,
    namespace: str,
    pod_name: str
) -> Dict:
    """Get detailed status summary for a pod."""
    try:
        pod = await api.read_namespaced_pod(name=pod_name, namespace=namespace)
        
        # Get pod events
        events = []
        try:
            event_list = await api.list_namespaced_event(
                namespace=namespace,
                field_selector=f"involvedObject.name={pod_name}"
            )
            events = [
                {
                    "type": e.type,
                    "reason": e.reason,
                    "message": e.message,
                    "timestamp": e.first_timestamp.isoformat() if e.first_timestamp else None
                }
                for e in event_list.items[:5]  # Last 5 events
            ]
        except Exception:
            pass
        
        # Container statuses
        container_statuses = []
        if pod.status.container_statuses:
            for cs in pod.status.container_statuses:
                state_info = {}
                if cs.state:
                    if cs.state.running:
                        state_info = {"state": "Running", "started": cs.state.running.started_at.isoformat() if cs.state.running.started_at else None}
                    elif cs.state.waiting:
                        state_info = {"state": "Waiting", "reason": cs.state.waiting.reason, "message": cs.state.waiting.message}
                    elif cs.state.terminated:
                        state_info = {"state": "Terminated", "reason": cs.state.terminated.reason, "exit_code": cs.state.terminated.exit_code}
                
                container_statuses.append({
                    "name": cs.name,
                    "ready": cs.ready,
                    "restart_count": cs.restart_count,
                    **state_info
                })
        
        return {
            "name": pod_name,
            "phase": pod.status.phase,
            "conditions": [
                {
                    "type": c.type,
                    "status": c.status,
                    "reason": c.reason,
                    "message": c.message
                }
                for c in (pod.status.conditions or [])
            ],
            "container_statuses": container_statuses,
            "events": events
        }
    except Exception as e:
        logger.warning(f"Error getting status for pod '{pod_name}': {e}")
        return {"name": pod_name, "error": str(e)}


async def verify_pod_logs(
    api: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    container_name: Optional[str] = None,
    lines: int = 5
) -> Tuple[bool, List[str]]:
    """Verify that a pod is generating logs.
    
    Returns:
        Tuple of (success: bool, log_lines: List[str])
    """
    try:
        log_stream = await api.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container_name,
            tail_lines=lines,
            timestamps=False
        )
        
        log_lines = log_stream.strip().split('\n') if log_stream else []
        if log_lines:
            logger.debug(f"Pod '{pod_name}' is generating logs ({len(log_lines)} lines retrieved)")
            return True, log_lines
        else:
            logger.warning(f"Pod '{pod_name}' has no logs yet")
            return False, []
    except Exception as e:
        logger.warning(f"Error reading logs from pod '{pod_name}': {e}")
        return False, []


# ============================================================================
# Pod Creation Functions
# ============================================================================

async def create_pod(
    api: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    containers: List[client.V1Container],
    labels: Dict[str, str],
    annotations: Optional[Dict[str, str]] = None,
    wait_timeout: int = DEFAULT_WAIT_TIMEOUT,
    check_containers: bool = True,
    continue_on_error: bool = False
) -> Tuple[bool, Optional[str], Optional[Dict]]:
    """Create a pod and wait for it to be ready.
    
    Returns:
        Tuple of (success: bool, pod_name: Optional[str], status: Optional[Dict])
    """
    pod = client.V1Pod(
        metadata=create_pod_metadata(pod_name, namespace, labels, annotations),
        spec=client.V1PodSpec(
            containers=containers,
            restart_policy="Always"
        )
    )
    
    logger.info(f"Creating pod '{pod_name}'...")
    start_time = time.time()
    
    try:
        await api.create_namespaced_pod(namespace=namespace, body=pod)
    except client.ApiException as e:
        if e.status == 409:
            logger.info(f"Pod '{pod_name}' already exists, checking status...")
            success, pod_obj = await wait_for_pod_running(api, namespace, pod_name, wait_timeout, check_containers)
            if not success:
                if continue_on_error:
                    logger.warning(f"Existing pod '{pod_name}' is not in Running state, but continuing...")
                    return False, pod_name, None
                raise RuntimeError(f"Existing pod '{pod_name}' is not in Running state")
            creation_time = time.time() - start_time
            status = await get_pod_status_summary(api, namespace, pod_name)
            return True, pod_name, {**status, "creation_time": creation_time}
        else:
            if continue_on_error:
                logger.error(f"Error creating pod '{pod_name}': {e}, but continuing...")
                return False, pod_name, None
            raise
    
    success, pod_obj = await wait_for_pod_running(api, namespace, pod_name, wait_timeout, check_containers)
    creation_time = time.time() - start_time
    
    if not success:
        # Get error details
        status = await get_pod_status_summary(api, namespace, pod_name)
        if continue_on_error:
            logger.warning(f"Pod '{pod_name}' failed to reach Running state, but continuing...")
            return False, pod_name, status
        raise RuntimeError(f"Pod '{pod_name}' failed to reach Running state")
    
    status = await get_pod_status_summary(api, namespace, pod_name)
    return True, pod_name, {**status, "creation_time": creation_time}


def create_json_logger_1_spec(
    image: str = DEFAULT_IMAGE,
    resources: Optional[client.V1ResourceRequirements] = None,
    security_context: Optional[client.V1SecurityContext] = None
) -> Tuple[str, List[client.V1Container], Dict[str, str]]:
    """Create spec for JSON Logger 1 pod."""
    pod_name = "json-logger-1"
    
    container = create_container(
        name="logger",
        image=image,
        command=["/bin/sh", "-c"],
        args=[
            """i=0; while true; do
  echo "{\\"level\\":\\"INFO\\",\\"msg\\":\\"JSON log message $i\\",\\"count\\":$i,\\"timestamp\\":\\"$(date -Iseconds)\\"}"
  i=$((i + 1))
  sleep 1
done"""
        ],
        resources=resources,
        security_context=security_context
    )
    
    labels = {"app": "json-logger", "type": "test"}
    return pod_name, [container], labels


def create_json_logger_2_spec(
    image: str = DEFAULT_IMAGE,
    resources: Optional[client.V1ResourceRequirements] = None,
    security_context: Optional[client.V1SecurityContext] = None
) -> Tuple[str, List[client.V1Container], Dict[str, str]]:
    """Create spec for JSON Logger 2 pod."""
    pod_name = "json-logger-2"
    
    container = create_container(
        name="logger",
        image=image,
        command=["/bin/sh", "-c"],
        args=[
            """i=0; while true; do
  level="INFO"
  if [ $((i % 5)) -eq 0 ]; then level="ERROR"; fi
  if [ $((i % 3)) -eq 0 ]; then level="WARN"; fi
  echo "{\\"level\\":\\"$level\\",\\"msg\\":\\"Log message $i\\",\\"count\\":$i,\\"service\\":\\"api-server\\"}"
  i=$((i + 1))
  sleep 1
done"""
        ],
        resources=resources,
        security_context=security_context
    )
    
    labels = {"app": "json-logger", "type": "test"}
    return pod_name, [container], labels


def create_plain_logger_1_spec(
    image: str = DEFAULT_IMAGE,
    resources: Optional[client.V1ResourceRequirements] = None,
    security_context: Optional[client.V1SecurityContext] = None
) -> Tuple[str, List[client.V1Container], Dict[str, str]]:
    """Create spec for Plain Text Logger 1 pod."""
    pod_name = "plain-logger-1"
    
    container = create_container(
        name="logger",
        image=image,
        command=["/bin/sh", "-c"],
        args=[
            """i=0; while true; do
  echo "Plain text log message $i"
  i=$((i + 1))
  sleep 1
done"""
        ],
        resources=resources,
        security_context=security_context
    )
    
    labels = {"app": "plain-logger", "type": "test"}
    return pod_name, [container], labels


def create_plain_logger_2_spec(
    image: str = DEFAULT_IMAGE,
    resources: Optional[client.V1ResourceRequirements] = None,
    security_context: Optional[client.V1SecurityContext] = None
) -> Tuple[str, List[client.V1Container], Dict[str, str]]:
    """Create spec for Plain Text Logger 2 pod."""
    pod_name = "plain-logger-2"
    
    container = create_container(
        name="logger",
        image=image,
        command=["/bin/sh", "-c"],
        args=[
            """i=0; while true; do
  echo "[$(date +%H:%M:%S)] INFO: Application processing request $i"
  i=$((i + 1))
  sleep 1
  if [ $((i % 3)) -eq 0 ]; then
    echo "[$(date +%H:%M:%S)] WARNING: High memory usage detected"
  fi
  if [ $((i % 7)) -eq 0 ]; then
    echo "[$(date +%H:%M:%S)] ERROR: Failed to connect to database"
  fi
done"""
        ],
        resources=resources,
        security_context=security_context
    )
    
    labels = {"app": "plain-logger", "type": "test"}
    return pod_name, [container], labels


def create_mixed_logger_spec(
    image: str = DEFAULT_IMAGE,
    resources: Optional[client.V1ResourceRequirements] = None,
    security_context: Optional[client.V1SecurityContext] = None
) -> Tuple[str, List[client.V1Container], Dict[str, str]]:
    """Create spec for Mixed Logger pod."""
    pod_name = "mixed-logger-1"
    
    container = create_container(
        name="logger",
        image=image,
        command=["/bin/sh", "-c"],
        args=[
            """i=0; while true; do
  if [ $((i % 2)) -eq 0 ]; then
    echo "{\\"level\\":\\"INFO\\",\\"msg\\":\\"Mixed logger - JSON format $i\\",\\"count\\":$i}"
  else
    echo "Mixed logger - Plain text format $i"
  fi
  i=$((i + 1))
  sleep 1
done"""
        ],
        resources=resources,
        security_context=security_context
    )
    
    labels = {"app": "mixed-logger", "type": "test"}
    return pod_name, [container], labels


def create_multi_container_pod_spec(
    image: str = DEFAULT_IMAGE,
    resources: Optional[client.V1ResourceRequirements] = None,
    security_context: Optional[client.V1SecurityContext] = None
) -> Tuple[str, List[client.V1Container], Dict[str, str]]:
    """Create spec for multi-container pod."""
    pod_name = "multi-container-pod"
    
    main_container = create_container(
        name="main",
        image=image,
        command=["/bin/sh", "-c"],
        args=[
            """i=0; while true; do
  echo "{\\"level\\":\\"INFO\\",\\"container\\":\\"main\\",\\"msg\\":\\"Main container processing request $i\\",\\"count\\":$i}"
  i=$((i + 1))
  sleep 2
done"""
        ],
        resources=resources,
        security_context=security_context
    )
    
    sidecar_container = create_container(
        name="sidecar",
        image=image,
        command=["/bin/sh", "-c"],
        args=[
            """i=0; while true; do
  echo "[Sidecar] Syncing data batch $i"
  i=$((i + 1))
  sleep 3
done"""
        ],
        resources=resources,
        security_context=security_context
    )
    
    labels = {"app": "multi-container", "type": "test"}
    return pod_name, [main_container, sidecar_container], labels


# ============================================================================
# Deployment Creation (Advanced Workload Type)
# ============================================================================

async def create_deployment(
    api: client.AppsV1Api,
    namespace: str,
    deployment_name: str,
    containers: List[client.V1Container],
    labels: Dict[str, str],
    annotations: Optional[Dict[str, str]] = None,
    replicas: int = 1,
    wait_timeout: int = DEFAULT_WAIT_TIMEOUT
) -> Tuple[bool, Optional[str]]:
    """Create a Deployment instead of a Pod."""
    deployment = client.V1Deployment(
        metadata=create_pod_metadata(deployment_name, namespace, labels, annotations),
        spec=client.V1DeploymentSpec(
            replicas=replicas,
            selector=client.V1LabelSelector(match_labels=labels),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels),
                spec=client.V1PodSpec(
                    containers=containers,
                    restart_policy="Always"
                )
            )
        )
    )
    
    logger.info(f"Creating Deployment '{deployment_name}' with {replicas} replica(s)...")
    
    try:
        await api.create_namespaced_deployment(namespace=namespace, body=deployment)
        logger.info(f"Deployment '{deployment_name}' created successfully")
        return True, deployment_name
    except client.ApiException as e:
        if e.status == 409:
            logger.info(f"Deployment '{deployment_name}' already exists")
            return True, deployment_name
        raise


async def create_statefulset(
    api: client.AppsV1Api,
    core_api: client.CoreV1Api,
    namespace: str,
    statefulset_name: str,
    containers: List[client.V1Container],
    labels: Dict[str, str],
    annotations: Optional[Dict[str, str]] = None,
    replicas: int = 1,
    wait_timeout: int = DEFAULT_WAIT_TIMEOUT
) -> Tuple[bool, Optional[str]]:
    """Create a StatefulSet instead of a Pod."""
    service_name = f"{statefulset_name}-service"
    
    # Create headless service for StatefulSet
    service = client.V1Service(
        metadata=client.V1ObjectMeta(
            name=service_name,
            namespace=namespace,
            labels=labels
        ),
        spec=client.V1ServiceSpec(
            cluster_ip="None",  # Headless service
            selector=labels,
            ports=[client.V1ServicePort(port=80, name="http")]
        )
    )
    
    try:
        await core_api.create_namespaced_service(namespace=namespace, body=service)
        logger.debug(f"Service '{service_name}' created for StatefulSet")
    except client.ApiException as e:
        if e.status != 409:
            raise
    
    # Create StatefulSet
    statefulset = client.V1StatefulSet(
        metadata=create_pod_metadata(statefulset_name, namespace, labels, annotations),
        spec=client.V1StatefulSetSpec(
            service_name=service_name,
            replicas=replicas,
            selector=client.V1LabelSelector(match_labels=labels),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels),
                spec=client.V1PodSpec(
                    containers=containers,
                    restart_policy="Always"
                )
            )
        )
    )
    
    logger.info(f"Creating StatefulSet '{statefulset_name}' with {replicas} replica(s)...")
    
    try:
        await api.create_namespaced_stateful_set(namespace=namespace, body=statefulset)
        logger.info(f"StatefulSet '{statefulset_name}' created successfully")
        return True, statefulset_name
    except client.ApiException as e:
        if e.status == 409:
            logger.info(f"StatefulSet '{statefulset_name}' already exists")
            return True, statefulset_name
        raise


async def create_daemonset(
    api: client.AppsV1Api,
    namespace: str,
    daemonset_name: str,
    containers: List[client.V1Container],
    labels: Dict[str, str],
    annotations: Optional[Dict[str, str]] = None,
    wait_timeout: int = DEFAULT_WAIT_TIMEOUT
) -> Tuple[bool, Optional[str]]:
    """Create a DaemonSet instead of a Pod."""
    daemonset = client.V1DaemonSet(
        metadata=create_pod_metadata(daemonset_name, namespace, labels, annotations),
        spec=client.V1DaemonSetSpec(
            selector=client.V1LabelSelector(match_labels=labels),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels),
                spec=client.V1PodSpec(
                    containers=containers,
                    restart_policy="Always"
                )
            )
        )
    )
    
    logger.info(f"Creating DaemonSet '{daemonset_name}'...")
    
    try:
        await api.create_namespaced_daemon_set(namespace=namespace, body=daemonset)
        logger.info(f"DaemonSet '{daemonset_name}' created successfully")
        return True, daemonset_name
    except client.ApiException as e:
        if e.status == 409:
            logger.info(f"DaemonSet '{daemonset_name}' already exists")
            return True, daemonset_name
        raise


# ============================================================================
# Parallel Pod Creation
# ============================================================================

async def create_all_pods(
    api: client.CoreV1Api,
    namespace: str,
    image: str = DEFAULT_IMAGE,
    use_resources: bool = True,
    use_security_context: bool = True,
    parallel: int = DEFAULT_PARALLEL,
    wait_timeout: int = DEFAULT_WAIT_TIMEOUT,
    check_containers: bool = True,
    continue_on_error: bool = False,
    use_deployments: bool = False,
    use_statefulsets: bool = False,
    use_daemonsets: bool = False,
    replicas: int = 1
) -> List[Tuple[bool, Optional[str], Optional[Dict]]]:
    """Create all test pods, optionally in parallel."""
    # Prepare resources and security context
    resources = create_resource_requirements() if use_resources else None
    security_context = create_security_context(read_only_root_filesystem=False) if use_security_context else None
    
    # Get all pod specs
    pod_specs = [
        create_json_logger_1_spec(image, resources, security_context),
        create_json_logger_2_spec(image, resources, security_context),
        create_plain_logger_1_spec(image, resources, security_context),
        create_plain_logger_2_spec(image, resources, security_context),
        create_mixed_logger_spec(image, resources, security_context),
        create_multi_container_pod_spec(image, resources, security_context),
    ]
    
    apps_api = client.AppsV1Api(api.api_client)
    
    if use_deployments:
        # Use Deployments API
        results = []
        for pod_name, containers, labels in pod_specs:
            try:
                success, name = await create_deployment(
                    apps_api, namespace, pod_name, containers, labels,
                    replicas=replicas, wait_timeout=wait_timeout
                )
                results.append((success, name, None))
            except Exception as e:
                logger.error(f"Error creating deployment '{pod_name}': {e}")
                if continue_on_error:
                    results.append((False, pod_name, None))
                else:
                    raise
        return results
    elif use_statefulsets:
        # Use StatefulSets API
        results = []
        for pod_name, containers, labels in pod_specs:
            try:
                success, name = await create_statefulset(
                    apps_api, api, namespace, pod_name, containers, labels,
                    replicas=replicas, wait_timeout=wait_timeout
                )
                results.append((success, name, None))
            except Exception as e:
                logger.error(f"Error creating statefulset '{pod_name}': {e}")
                if continue_on_error:
                    results.append((False, pod_name, None))
                else:
                    raise
        return results
    elif use_daemonsets:
        # Use DaemonSets API
        results = []
        for pod_name, containers, labels in pod_specs:
            try:
                success, name = await create_daemonset(
                    apps_api, namespace, pod_name, containers, labels,
                    wait_timeout=wait_timeout
                )
                results.append((success, name, None))
            except Exception as e:
                logger.error(f"Error creating daemonset '{pod_name}': {e}")
                if continue_on_error:
                    results.append((False, pod_name, None))
                else:
                    raise
        return results
    else:
        # Use Pods API with optional parallelization
        if parallel > 1:
            semaphore = asyncio.Semaphore(parallel)
            
            async def create_with_semaphore(pod_name, containers, labels):
                async with semaphore:
                    return await create_pod(
                        api, namespace, pod_name, containers, labels,
                        wait_timeout=wait_timeout,
                        check_containers=check_containers,
                        continue_on_error=continue_on_error
                    )
            
            tasks = [
                create_with_semaphore(pod_name, containers, labels)
                for pod_name, containers, labels in pod_specs
            ]
            return await asyncio.gather(*tasks, return_exceptions=False)
        else:
            # Sequential creation
            results = []
            for pod_name, containers, labels in pod_specs:
                try:
                    result = await create_pod(
                        api, namespace, pod_name, containers, labels,
                        wait_timeout=wait_timeout,
                        check_containers=check_containers,
                        continue_on_error=continue_on_error
                    )
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error creating pod '{pod_name}': {e}")
                    if continue_on_error:
                        results.append((False, pod_name, None))
                    else:
                        raise
            return results


# ============================================================================
# Cleanup Functions
# ============================================================================

async def cleanup_pods_and_namespace(
    api: client.CoreV1Api,
    namespace: str,
    force: bool = False
) -> None:
    """Delete all pods and the namespace."""
    grace_period = 0 if force else None
    
    logger.info(f"Deleting pods in namespace '{namespace}'...")
    if force:
        logger.info("Force mode enabled (grace_period=0)")
    
    # Delete Deployments, StatefulSets, and DaemonSets first if they exist
    try:
        apps_api = client.AppsV1Api(api.api_client)
        
        # Delete Deployments
        try:
            deployments = await apps_api.list_namespaced_deployment(namespace=namespace)
            for deployment in deployments.items:
                try:
                    await apps_api.delete_namespaced_deployment(
                        name=deployment.metadata.name,
                        namespace=namespace,
                        grace_period_seconds=grace_period
                    )
                    logger.info(f"Deployment '{deployment.metadata.name}' deleted")
                except Exception as e:
                    logger.warning(f"Error deleting deployment '{deployment.metadata.name}': {e}")
        except Exception as e:
            logger.debug(f"Error listing deployments: {e}")
        
        # Delete StatefulSets
        try:
            statefulsets = await apps_api.list_namespaced_stateful_set(namespace=namespace)
            for statefulset in statefulsets.items:
                try:
                    await apps_api.delete_namespaced_stateful_set(
                        name=statefulset.metadata.name,
                        namespace=namespace,
                        grace_period_seconds=grace_period
                    )
                    logger.info(f"StatefulSet '{statefulset.metadata.name}' deleted")
                except Exception as e:
                    logger.warning(f"Error deleting statefulset '{statefulset.metadata.name}': {e}")
        except Exception as e:
            logger.debug(f"Error listing statefulsets: {e}")
        
        # Delete DaemonSets
        try:
            daemonsets = await apps_api.list_namespaced_daemon_set(namespace=namespace)
            for daemonset in daemonsets.items:
                try:
                    await apps_api.delete_namespaced_daemon_set(
                        name=daemonset.metadata.name,
                        namespace=namespace,
                        grace_period_seconds=grace_period
                    )
                    logger.info(f"DaemonSet '{daemonset.metadata.name}' deleted")
                except Exception as e:
                    logger.warning(f"Error deleting daemonset '{daemonset.metadata.name}': {e}")
        except Exception as e:
            logger.debug(f"Error listing daemonsets: {e}")
        
        # Delete Services (created for StatefulSets)
        try:
            services = await api.list_namespaced_service(namespace=namespace)
            for service in services.items:
                if service.metadata.name.endswith("-service"):
                    try:
                        await api.delete_namespaced_service(
                            name=service.metadata.name,
                            namespace=namespace
                        )
                        logger.debug(f"Service '{service.metadata.name}' deleted")
                    except Exception as e:
                        logger.debug(f"Error deleting service '{service.metadata.name}': {e}")
        except Exception as e:
            logger.debug(f"Error listing services: {e}")
    except Exception as e:
        logger.debug(f"Error accessing Apps API: {e}")
    
    # Delete Pods
    try:
        pods = await api.list_namespaced_pod(namespace=namespace)
        for pod in pods.items:
            try:
                await api.delete_namespaced_pod(
                    name=pod.metadata.name,
                    namespace=namespace,
                    grace_period_seconds=grace_period
                )
                logger.info(f"Pod '{pod.metadata.name}' deleted")
            except Exception as e:
                logger.warning(f"Error deleting pod '{pod.metadata.name}': {e}")
    except client.ApiException as e:
        if e.status != 404:
            logger.warning(f"Error listing pods: {e}")
    
    # Delete namespace
    logger.info(f"Deleting namespace '{namespace}'...")
    try:
        await api.delete_namespace(
            name=namespace,
            grace_period_seconds=grace_period
        )
        logger.info(f"Namespace '{namespace}' deleted successfully")
    except client.ApiException as e:
        if e.status == 404:
            logger.info(f"Namespace '{namespace}' does not exist")
        else:
            logger.error(f"Error deleting namespace: {e}")
            raise


# ============================================================================
# Status Display Functions
# ============================================================================

def print_status_summary(results: List[Tuple[bool, Optional[str], Optional[Dict]]]) -> None:
    """Print a formatted status summary of pod creation results."""
    logger.info("\n" + "="*80)
    logger.info("POD CREATION SUMMARY")
    logger.info("="*80)
    
    successful = [r for r in results if r[0]]
    failed = [r for r in results if not r[0]]
    
    logger.info(f"\nTotal: {len(results)} | Successful: {len(successful)} | Failed: {len(failed)}")
    
    if successful:
        logger.info("\n✓ Successful Pods:")
        for success, pod_name, status in successful:
            if pod_name:
                creation_time = status.get("creation_time", 0) if status else 0
                logger.info(f"  • {pod_name:<30} (Phase: {status.get('phase', 'Unknown') if status else 'Unknown'}, Time: {creation_time:.2f}s)")
    
    if failed:
        logger.info("\n✗ Failed Pods:")
        for success, pod_name, status in failed:
            if pod_name:
                phase = status.get("phase", "Unknown") if status else "Unknown"
                logger.info(f"  • {pod_name:<30} (Phase: {phase})")
                if status and status.get("events"):
                    for event in status["events"][:2]:  # Show first 2 events
                        logger.info(f"    - {event.get('type', 'Unknown')}: {event.get('reason', 'Unknown')} - {event.get('message', '')}")


def print_detailed_status(results: List[Tuple[bool, Optional[str], Optional[Dict]]]) -> None:
    """Print detailed status for each pod."""
    logger.info("\n" + "="*80)
    logger.info("DETAILED POD STATUS")
    logger.info("="*80)
    
    for success, pod_name, status in results:
        if not pod_name or not status:
            continue
            
        logger.info(f"\nPod: {pod_name}")
        logger.info(f"  Phase: {status.get('phase', 'Unknown')}")
        
        if status.get("conditions"):
            logger.info("  Conditions:")
            for cond in status["conditions"]:
                logger.info(f"    - {cond['type']}: {cond['status']} ({cond.get('reason', 'N/A')})")
        
        if status.get("container_statuses"):
            logger.info("  Containers:")
            for cs in status["container_statuses"]:
                logger.info(f"    - {cs['name']}: {cs.get('state', 'Unknown')} (Ready: {cs.get('ready', False)}, Restarts: {cs.get('restart_count', 0)})")
        
        if status.get("events"):
            logger.info("  Recent Events:")
            for event in status["events"][:3]:
                logger.info(f"    - [{event.get('type', 'Unknown')}] {event.get('reason', 'Unknown')}: {event.get('message', '')}")


# ============================================================================
# Main Function
# ============================================================================

async def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Create test pods in a namespace to test KuLo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create pods with default settings
  python scripts/setup_demo.py

  # Create pods in parallel with resource limits
  python scripts/setup_demo.py --parallel 5 --verify-logs --show-status

  # Create Deployments instead of Pods
  python scripts/setup_demo.py --use-deployments --replicas 2

  # Create StatefulSets instead of Pods
  python scripts/setup_demo.py --use-statefulsets --replicas 2

  # Create DaemonSets instead of Pods
  python scripts/setup_demo.py --use-daemonsets
        """
    )
    parser.add_argument(
        "-n", "--namespace",
        default=DEFAULT_NAMESPACE,
        help=f"Namespace where to create pods (default: {DEFAULT_NAMESPACE})"
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete all pods and the namespace"
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Force delete (grace_period=0) when doing cleanup"
    )
    parser.add_argument(
        "-t", "--timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Wait N seconds after creating pods and then perform automatic cleanup"
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=DEFAULT_PARALLEL,
        metavar="N",
        help=f"Number of pods to create concurrently (default: {DEFAULT_PARALLEL})"
    )
    parser.add_argument(
        "--verify-logs",
        action="store_true",
        help="Verify that pods are generating logs after creation"
    )
    parser.add_argument(
        "--show-status",
        action="store_true",
        help="Show detailed pod status after creation"
    )
    parser.add_argument(
        "--use-deployments",
        action="store_true",
        help="Create Deployments instead of bare Pods"
    )
    parser.add_argument(
        "--use-statefulsets",
        action="store_true",
        help="Create StatefulSets instead of bare Pods"
    )
    parser.add_argument(
        "--use-daemonsets",
        action="store_true",
        help="Create DaemonSets instead of bare Pods"
    )
    parser.add_argument(
        "--replicas",
        type=int,
        default=1,
        metavar="N",
        help="Number of replicas when using Deployments or StatefulSets (default: 1)"
    )
    parser.add_argument(
        "--image",
        type=str,
        default=DEFAULT_IMAGE,
        help=f"Container image to use (default: {DEFAULT_IMAGE})"
    )
    parser.add_argument(
        "--no-resources",
        action="store_true",
        help="Don't set resource requests/limits on containers"
    )
    parser.add_argument(
        "--no-security-context",
        action="store_true",
        help="Don't set security context on containers"
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue creating other pods if one fails"
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=DEFAULT_WAIT_TIMEOUT,
        metavar="SECONDS",
        help=f"Timeout for waiting for pods to be ready (default: {DEFAULT_WAIT_TIMEOUT})"
    )
    parser.add_argument(
        "--no-container-check",
        action="store_true",
        help="Don't verify container readiness, only pod phase"
    )
    
    args = parser.parse_args()
    namespace = args.namespace
    
    # Create API client properly
    api_client = None
    try:
        await config.load_kube_config()
        api_client = client.ApiClient()
        api = client.CoreV1Api(api_client)
    except Exception as e:
        logger.error(f"Error loading Kubernetes configuration: {e}")
        sys.exit(1)
    
    try:
        if args.cleanup:
            await cleanup_pods_and_namespace(api, namespace, force=args.force)
        else:
            # Ensure namespace exists
            await ensure_namespace(api, namespace)
            
            # Create all pods
            results = await create_all_pods(
                api=api,
                namespace=namespace,
                image=args.image,
                use_resources=not args.no_resources,
                use_security_context=not args.no_security_context,
                parallel=args.parallel,
                wait_timeout=args.wait_timeout,
                check_containers=not args.no_container_check,
                continue_on_error=args.continue_on_error,
                use_deployments=args.use_deployments,
                use_statefulsets=args.use_statefulsets,
                use_daemonsets=args.use_daemonsets,
                replicas=args.replicas
            )
            
            # Print status summary
            print_status_summary(results)
            
            # Show detailed status if requested
            if args.show_status:
                print_detailed_status(results)
            
            # Verify logs if requested
            if args.verify_logs:
                logger.info("\n" + "="*80)
                logger.info("VERIFYING LOGS")
                logger.info("="*80)
                for success, pod_name, status in results:
                    if success and pod_name:
                        # For multi-container pods, check each container
                        if status and status.get("container_statuses"):
                            for cs in status["container_statuses"]:
                                log_success, log_lines = await verify_pod_logs(
                                    api, namespace, pod_name, cs["name"], lines=3
                                )
                                if log_success and log_lines:
                                    logger.info(f"✓ {pod_name}/{cs['name']}: {len(log_lines)} log lines retrieved")
                                    for line in log_lines[:2]:  # Show first 2 lines
                                        logger.info(f"    {line[:80]}")
                                else:
                                    logger.warning(f"✗ {pod_name}/{cs['name']}: No logs available")
                        else:
                            log_success, log_lines = await verify_pod_logs(
                                api, namespace, pod_name, None, lines=3
                            )
                            if log_success and log_lines:
                                logger.info(f"✓ {pod_name}: {len(log_lines)} log lines retrieved")
                                for line in log_lines[:2]:
                                    logger.info(f"    {line[:80]}")
                            else:
                                logger.warning(f"✗ {pod_name}: No logs available")
            
            # Print usage instructions
            successful_pods = [r[1] for r in results if r[0] and r[1]]
            if successful_pods:
                logger.info("\n" + "="*80)
                logger.info("USAGE INSTRUCTIONS")
                logger.info("="*80)
                logger.info(f"\nTo test KuLo, run:")
                logger.info(f"  kulo -n {namespace} -f")
                logger.info(f"\nTo filter by logger type:")
                logger.info(f"  kulo -n {namespace} -l app=json-logger -f")
                logger.info(f"  kulo -n {namespace} -l app=plain-logger -f")
                logger.info(f"  kulo -n {namespace} -l app=mixed-logger -f")
                logger.info(f"  kulo -n {namespace} -l app=multi-container -f")
                logger.info(f"\nTo cleanup, run:")
                logger.info(f"  python scripts/setup_demo.py -n {namespace} --cleanup")
                if args.force:
                    logger.info(f"  python scripts/setup_demo.py -n {namespace} --cleanup --force")
                logger.info("="*80)
            
            # If timeout specified, wait and then cleanup
            if args.timeout is not None:
                logger.info(f"\nWaiting {args.timeout} seconds before automatic cleanup...")
                logger.info("Press Ctrl+C to cancel automatic cleanup")
                try:
                    await asyncio.sleep(args.timeout)
                    logger.info("\nTimeout reached. Executing automatic cleanup...")
                    await cleanup_pods_and_namespace(api, namespace, force=args.force)
                except asyncio.CancelledError:
                    logger.info("\nAutomatic cleanup cancelled by user")
                    # Don't re-raise, just exit gracefully
                    return
    except KeyboardInterrupt:
        logger.info("\nOperation cancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error during execution: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if api_client:
            await api_client.close()


if __name__ == "__main__":
    asyncio.run(main())
