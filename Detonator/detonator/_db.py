import time
from functools import wraps
from typing import Callable, TypeVar

import pymongo.errors
from mongoengine import connect, disconnect, get_connection
from mongoengine.connection import DEFAULT_CONNECTION_NAME

from ._env import is_prod
from ._log import get_logger

DEF_MONGO_HOST = 'miner-mongodb'
DEF_MONGO_PORT = 27017
DEF_MONGO_DB = 'mongogo'
_logger = get_logger('db')

# Retry configuration for MongoDB operations
MONGO_RETRY_MAX_ATTEMPTS = 3
MONGO_RETRY_BASE_DELAY = 1.0  # seconds
MONGO_RETRY_MAX_DELAY = 10.0  # seconds

T = TypeVar('T')


def close_db_connection(alias: str = DEFAULT_CONNECTION_NAME):
    """
    Close MongoDB connection for the given alias.
    Useful for cleaning up stale connections after forking.
    """
    try:
        disconnect(alias=alias)
        _logger.debug(f'Closed MongoDB connection for alias: {alias}')
    except Exception as e:
        _logger.debug(f'Error closing MongoDB connection for alias {alias}: {e}')


def make_db_connection(db: str = DEF_MONGO_DB, host: str = DEF_MONGO_HOST, port=DEF_MONGO_PORT,
                       alias: str = DEFAULT_CONNECTION_NAME, force_reconnect: bool = False):
    """
    Create or get MongoDB connection. If force_reconnect is True, close existing connection first.
    
    Args:
        db: Database name
        host: MongoDB host
        port: MongoDB port
        alias: Connection alias
        force_reconnect: If True, close existing connection before creating new one
    """
    if force_reconnect:
        close_db_connection(alias=alias)
    
    try:
        conn = get_connection(alias=alias)
        # get_connection() returns a pymongo.MongoClient directly — ping it to verify it's alive
        conn.admin.command('ping')
        return  # Connection is healthy, nothing to do
    except Exception:
        # Connection doesn't exist or is stale — close any remnant before reconnecting
        close_db_connection(alias=alias)
        prod = is_prod()
        _logger.info('Connecting to mongodb database prod: %s', prod)
        connect(
            db=db if prod else 'mongogo-test',
            host=host if prod else 'localhost',
            port=port,
            alias=alias,
            uuidRepresentation='standard',
            # Connection pool size
            maxPoolSize=16,
            minPoolSize=8,
            # Connection timeout settings
            connectTimeoutMS=30000,  # 30 seconds to establish connection
            socketTimeoutMS=60000,  # 60 seconds for socket operations
            serverSelectionTimeoutMS=30000,  # 30 seconds to select server
            # Connection health and lifecycle
            maxIdleTimeMS=300000,  # 5 minutes - close idle connections
            waitQueueTimeoutMS=30000,  # 30 seconds max wait for connection from pool
            # Heartbeat settings for connection health checks
            heartbeatFrequencyMS=10000,  # 10 seconds between heartbeats
            # Retry settings
            retryWrites=True,
            retryReads=True,
        )


def ensure_db_connection(_func=None, *, db: str = DEF_MONGO_DB, host: str = DEF_MONGO_HOST, port=DEF_MONGO_PORT,
                         alias: str = DEFAULT_CONNECTION_NAME):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            make_db_connection(db=db, host=host, port=port, alias=alias)
            return func(*args, **kwargs)
        return wrapper

    if _func is None:
        return decorator
    else:
        return decorator(_func)


def retry_mongo_operation(
    operation: Callable[[], T],
    max_attempts: int = MONGO_RETRY_MAX_ATTEMPTS,
    base_delay: float = MONGO_RETRY_BASE_DELAY,
    max_delay: float = MONGO_RETRY_MAX_DELAY,
    operation_name: str = "MongoDB operation"
) -> T:
    """
    Retry a MongoDB operation with exponential backoff on AutoReconnect and connection errors.

    Args:
        operation: The MongoDB operation to retry (callable that returns T)
        max_attempts: Maximum number of retry attempts (default: 3)
        base_delay: Base delay in seconds for exponential backoff (default: 1.0)
        max_delay: Maximum delay in seconds (default: 10.0)
        operation_name: Name of the operation for logging (default: "MongoDB operation")

    Returns:
        The result of the operation

    Raises:
        The last exception if all retry attempts fail
    """
    last_exception = None

    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except (pymongo.errors.AutoReconnect,
                pymongo.errors.ConnectionFailure,
                pymongo.errors.ServerSelectionTimeoutError,
                pymongo.errors.NetworkTimeout) as e:
            last_exception = e

            if attempt < max_attempts:
                # Exponential backoff with jitter
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                _logger.warning(
                    f'{operation_name} failed with {type(e).__name__}: {e}. '
                    f'Retrying in {delay:.2f}s (attempt {attempt}/{max_attempts})'
                )
                time.sleep(delay)

                # Try to refresh the connection
                try:
                    make_db_connection()
                except Exception as conn_err:
                    _logger.warning(
                        f'Failed to refresh MongoDB connection: {conn_err}')
            else:
                _logger.error(
                    f'{operation_name} failed after {max_attempts} attempts. '
                    f'Last error: {type(e).__name__}: {e}'
                )
        except Exception as e:
            # For non-connection errors, don't retry
            _logger.error(
                f'{operation_name} failed with non-retryable error: {type(e).__name__}: {e}')
            raise

    # If we exhausted all retries, raise the last exception
    if last_exception:
        raise last_exception
    else:
        raise RuntimeError(
            f'{operation_name} failed but no exception was captured')
