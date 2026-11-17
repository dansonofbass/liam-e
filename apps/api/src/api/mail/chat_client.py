"""Build Mistral clients for mail and chat content without content-bearing SDK spans or HTTP debug logging."""
import logging
from opentelemetry.trace import NoOpTracerProvider
from mistralai.extra.observability.telemetry import configure_telemetry
from utils.mistral import mistral_client as app_client


def mistral_client():
    client = app_client()
    configure_telemetry(client, provider=NoOpTracerProvider(), redaction=False)
    logger = logging.Logger('chat-private', level=logging.CRITICAL + 1)
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    client.sdk_configuration.debug_logger = logger
    return client
