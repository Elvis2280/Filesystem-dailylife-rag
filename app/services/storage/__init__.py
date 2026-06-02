"""Storage management service.

Handles file persistence (disk I/O), workspace lifecycle
(create/disable), and database record creation. Orchestrates
the initial file upload → DB record → Celery task dispatch flow.
"""
