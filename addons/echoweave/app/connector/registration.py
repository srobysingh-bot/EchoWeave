from __future__ import annotations

import logging

from app.connector.client import ConnectorClient

logger = logging.getLogger(__name__)


async def register_connector(client: ConnectorClient, *, ma_reachable: bool) -> bool:
    ok = await client.register(capabilities={"music_assistant": {"reachable": ma_reachable}})
    if ok:
        logger.info("Connector registration succeeded.")
    else:
        logger.warning("Connector registration failed.")
    return ok
