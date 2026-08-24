"""Periodic and background jobs.

These were Celery tasks until bnkscope Phase 4. They now run either on the
APScheduler instance owned by main.py's lifespan (periodic work) or on the
small thread pool in core/background.py (fire-and-forget work). Nothing here
is durable across a restart — see core/background.py.
"""
