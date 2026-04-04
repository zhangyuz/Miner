from celery import Celery
from celery.signals import worker_process_init
from detonator import get_logger
from detonator._db import close_db_connection, make_db_connection

from ._version import version

_logger = get_logger('MinerWorkers')

app = Celery('Miner')
app.config_from_object('minerworkers.celeryconfig')
app.autodiscover_tasks(['minerworkers'], force=True)


@worker_process_init.connect
def init_worker_process(**kwargs):
    """
    Initialize worker process after forking.
    This ensures MongoDB connections are created fresh in each worker process,
    avoiding stale connections from the parent process.
    """
    _logger.info('Worker process initialized, setting up MongoDB connection...')
    try:
        # Close any existing connections that might have been inherited from parent
        close_db_connection()
        # Create fresh connection in this worker process
        make_db_connection(force_reconnect=True)
        _logger.info('MongoDB connection initialized successfully in worker process')
    except Exception as e:
        _logger.error(f'Failed to initialize MongoDB connection in worker process: {e}', exc_info=True)


# @app.task
# def test_task_a():
#     _logger.error('This is test task a')


__all__ = [
    'version',
]
