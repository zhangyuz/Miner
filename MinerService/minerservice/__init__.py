from celery import Celery
from celery.schedules import crontab
from detonator import get_logger, is_prod
from minerworkers import app

from ._version import version
from .tasks import run_hk_daily_updates_task, run_us_daily_updates_task

__all__ = [
    'version'
]

_logger = get_logger('MinerService')

app.autodiscover_tasks(
    ['minerservice', 'minerservice.api.v1', 'marketbreadth'], force=True)


@app.on_after_configure.connect
def setup_periodic_tasks(sender: Celery, **_):
    """
    Set up periodic tasks for Celery Beat.
    This function is connected to the `on_after_configure` signal.
    """
    if not is_prod():
        _logger.info(
            'Skip setting up periodic tasks for non production environment')
        return
    _logger.info('Setting up miner service periodic tasks ...')
    sender.add_periodic_task(
        crontab(hour=16, minute=5, day_of_week='mon-fri'),
        run_us_daily_updates_task.s(),
        name='us-daily-updates-1605',
        expires=600,
    )

    sender.add_periodic_task(
        crontab(hour=5, minute=1, day_of_week='mon-fri'),
        run_hk_daily_updates_task.s(),
        name='hk-daily-updates-0501',
        expires=600,
    )
