from celery import Celery
from celery.schedules import crontab
from detonator import get_logger, is_prod
from minerworkers import app

from ._market_valuation_scraper import MarketValuationScraper
from ._version import __version__
from .tasks import update_market_pe_task

_logger = get_logger('BrowserScraper')


__all__ = [
    '__version__',
    'MarketValuationScraper'
]

app.autodiscover_tasks(['browserscraper'], force=True)


@app.on_after_configure.connect
def setup_periodic_tasks(sender: Celery, **kwargs):
    """
    Set up periodic tasks for Celery Beat.
    This function is connected to the `on_after_configure` signal.
    """
    if not is_prod():
        _logger.info(
            'Skipping setting up period task for non production environment')
        return
    # Add the daily update task.
    _logger.info(
        'Setting up periodic task for browserscraper ...')
    sender.add_periodic_task(
        crontab(hour='*', minute='5'),
        update_market_pe_task.s(),
        name='update-market-pe-daily',
        expires=600,
    )
