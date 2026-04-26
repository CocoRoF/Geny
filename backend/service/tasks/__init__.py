"""Background task runtime wiring (PR-A.5.3).

Service-level glue that picks the TaskRegistry backend, instantiates
the BackgroundTaskRunner with Geny's executors, and registers it on
``app.state``. Imported from ``main.py`` lifespan.
"""

from service.tasks.install import install_task_runtime

__all__ = ["install_task_runtime"]
