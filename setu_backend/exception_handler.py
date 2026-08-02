import logging

from rest_framework.views import exception_handler

logger = logging.getLogger('setu_backend')


def logging_exception_handler(exc, context):
    """
    Wraps DRF's default exception handler so every API exception is logged
    with the view/request that triggered it. 4xx (expected client errors —
    bad input, not-found, permission-denied) are logged at WARNING; anything
    DRF can't turn into a clean response (500s) is logged at ERROR so it's
    loud in the console and gets picked up by Sentry if configured.
    """
    response = exception_handler(exc, context)
    request = context.get('request')
    view = context.get('view')
    path = getattr(request, 'path', 'unknown')

    if response is not None:
        level = logging.ERROR if response.status_code >= 500 else logging.WARNING
        logger.log(level, 'API error %s on %s (%s): %s', response.status_code, path, view.__class__.__name__ if view else '?', exc)
    else:
        # Unhandled exception — DRF couldn't build a response at all.
        logger.exception('Unhandled exception on %s (%s)', path, view.__class__.__name__ if view else '?')

    return response
