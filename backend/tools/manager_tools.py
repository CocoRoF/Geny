"""
Manager Tools

Tools for Manager sessions to control and delegate tasks to Workers.
These tools allow a Manager to:
- List assigned workers
- Delegate tasks to workers
- Check worker status
- Get worker results

These tools are only available to Manager sessions.
"""
import os
import json
import httpx
from pathlib import Path
from typing import Optional, Tuple
from tools.base import tool

# Get the base URL for Geny Agent API
GENY_AGENT_URL = os.getenv("GENY_AGENT_URL", "http://localhost:8000")


def _get_session_info() -> Tuple[Optional[str], Optional[str]]:
    """
    Get current session info from .claude_session.json file.

    Returns:
        Tuple of (session_id, role) or (None, None) if not found
    """
    # Look for .claude_session.json in current directory or parent directories
    cwd = Path.cwd()

    for path in [cwd] + list(cwd.parents)[:3]:  # Check cwd and up to 3 parent dirs
        session_file = path / ".claude_session.json"
        if session_file.exists():
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    info = json.load(f)
                    return info.get("session_id"), info.get("role")
            except Exception:
                pass

    return None, None


def _get_manager_id() -> Optional[str]:
    """Get current manager session ID if this is a manager session."""
    session_id, role = _get_session_info()
    if role == "manager":
        return session_id
    return None


@tool
def list_workers() -> str:
    """
    List all workers assigned to this manager.

    Returns a list of workers with their current status.
    Use this to see which workers are available for task delegation.

    Returns:
        JSON string containing list of workers with their status
    """
    manager_id = _get_manager_id()
    if not manager_id:
        session_id, role = _get_session_info()
        if role and role != "manager":
            return json.dumps({"error": f"This session is a '{role}', not a manager. Only managers can list workers."})
        return json.dumps({"error": "Could not find session info. Make sure you're running in a Geny Agent session."})

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{GENY_AGENT_URL}/api/agents/{manager_id}/workers")
            response.raise_for_status()
            workers = response.json()

            if not workers:
                return json.dumps({
                    "message": "No workers assigned to this manager",
                    "workers": []
                })

            result = []
            for w in workers:
                result.append({
                    "worker_id": w.get("session_id"),
                    "name": w.get("session_name", "unnamed"),
                    "status": w.get("status"),
                    "is_busy": w.get("is_busy", False)
                })

            return json.dumps({
                "worker_count": len(result),
                "workers": result
            }, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to list workers: {str(e)}"})


@tool
def delegate_task(worker_name: str, task: str) -> str:
    """
    Delegate a task to a specific worker.

    The worker will execute the task and return the result.
    Use list_workers() first to see available workers.

    Args:
        worker_name: Name of the worker to delegate to (from list_workers)
        task: The task description/prompt for the worker to execute

    Returns:
        JSON string containing the worker's response or error
    """
    manager_id = _get_manager_id()
    if not manager_id:
        return json.dumps({"error": "Not running as a manager session"})

    if not task.strip():
        return json.dumps({"error": "Task cannot be empty"})

    try:
        with httpx.Client(timeout=300.0) as client:  # Long timeout for task execution
            # First, find the worker by name
            workers_response = client.get(f"{GENY_AGENT_URL}/api/agents/{manager_id}/workers")
            workers_response.raise_for_status()
            workers = workers_response.json()

            # Find worker by name
            worker = None
            for w in workers:
                if w.get("session_name") == worker_name or w.get("session_id") == worker_name:
                    worker = w
                    break

            if not worker:
                available = [w.get("session_name", w.get("session_id", "unknown")) for w in workers]
                return json.dumps({
                    "error": f"Worker '{worker_name}' not found",
                    "available_workers": available
                })

            worker_id = worker.get("session_id")

            if worker.get("status") != "running":
                return json.dumps({
                    "error": f"Worker '{worker_name}' is not running (status: {worker.get('status')})"
                })

            # Delegate the task
            delegate_response = client.post(
                f"{GENY_AGENT_URL}/api/agents/{manager_id}/delegate",
                json={
                    "worker_id": worker_id,
                    "prompt": task
                }
            )
            delegate_response.raise_for_status()
            result = delegate_response.json()

            if result.get("success"):
                return json.dumps({
                    "status": "completed",
                    "worker": worker_name,
                    "task": task[:100] + "..." if len(task) > 100 else task,
                    "output": result.get("output", "No output"),
                    "execution_time": result.get("execution_time")
                }, indent=2)
            else:
                return json.dumps({
                    "status": "failed",
                    "worker": worker_name,
                    "error": result.get("error", "Unknown error")
                })

    except httpx.TimeoutException:
        return json.dumps({
            "error": "Task execution timed out. The worker may still be processing."
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to delegate task: {str(e)}"})


@tool
def get_worker_status(worker_name: str) -> str:
    """
    Get the current status of a specific worker.

    Args:
        worker_name: Name of the worker to check

    Returns:
        JSON string containing worker status details
    """
    manager_id = _get_manager_id()
    if not manager_id:
        session_id, role = _get_session_info()
        if role and role != "manager":
            return json.dumps({"error": f"This session is a '{role}', not a manager."})
        return json.dumps({"error": "Could not find session info."})

    try:
        with httpx.Client(timeout=30.0) as client:
            workers_response = client.get(f"{GENY_AGENT_URL}/api/agents/{manager_id}/workers")
            workers_response.raise_for_status()
            workers = workers_response.json()

            for w in workers:
                if w.get("session_name") == worker_name or w.get("session_id") == worker_name:
                    return json.dumps({
                        "worker": w.get("session_name", worker_name),
                        "status": w.get("status"),
                        "is_busy": w.get("is_busy", False),
                        "current_task": w.get("current_task"),
                        "last_activity": w.get("last_activity")
                    }, indent=2)

            available = [w.get("session_name", w.get("session_id", "unknown")) for w in workers]
            return json.dumps({
                "error": f"Worker '{worker_name}' not found",
                "available_workers": available
            })

    except Exception as e:
        return json.dumps({"error": f"Failed to get worker status: {str(e)}"})


@tool
def broadcast_task(task: str) -> str:
    """
    Broadcast a task to all available workers.

    All idle workers will receive and execute the same task in parallel.

    Args:
        task: The task description/prompt for all workers to execute

    Returns:
        JSON string containing results from all workers
    """
    manager_id = _get_manager_id()
    if not manager_id:
        session_id, role = _get_session_info()
        if role and role != "manager":
            return json.dumps({"error": f"This session is a '{role}', not a manager."})
        return json.dumps({"error": "Could not find session info."})

    if not task.strip():
        return json.dumps({"error": "Task cannot be empty"})

    try:
        with httpx.Client(timeout=300.0) as client:
            # Get all workers
            workers_response = client.get(f"{GENY_AGENT_URL}/api/agents/{manager_id}/workers")
            workers_response.raise_for_status()
            workers = workers_response.json()

            # Filter to running, non-busy workers
            available_workers = [
                w for w in workers
                if w.get("status") == "running" and not w.get("is_busy", False)
            ]

            if not available_workers:
                return json.dumps({
                    "error": "No available workers",
                    "total_workers": len(workers),
                    "busy_workers": len([w for w in workers if w.get("is_busy", False)])
                })

            results = []
            for worker in available_workers:
                worker_id = worker.get("session_id")
                worker_name = worker.get("session_name", worker_id[:8])

                try:
                    delegate_response = client.post(
                        f"{GENY_AGENT_URL}/api/agents/{manager_id}/delegate",
                        json={
                            "worker_id": worker_id,
                            "prompt": task
                        }
                    )
                    delegate_response.raise_for_status()
                    result = delegate_response.json()

                    results.append({
                        "worker": worker_name,
                        "success": result.get("success", False),
                        "output": result.get("output", "")[:500] if result.get("output") else None,
                        "error": result.get("error")
                    })
                except Exception as e:
                    results.append({
                        "worker": worker_name,
                        "success": False,
                        "error": str(e)
                    })

            return json.dumps({
                "task": task[:100] + "..." if len(task) > 100 else task,
                "workers_executed": len(results),
                "successful": len([r for r in results if r.get("success")]),
                "results": results
            }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to broadcast task: {str(e)}"})


# MCP ?�버 ?�록???�한 TOOLS 리스??
TOOLS = [list_workers, delegate_task, get_worker_status, broadcast_task]
