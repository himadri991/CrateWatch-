import json
import logging
import os
import threading
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger("cratewatch.alerts")


def _send_webhook(url: str, payload: dict[str, Any]) -> None:
    try:
        httpx.post(url, json=payload, timeout=3.0)
    except Exception as exc:
        logger.warning("webhook delivery failed: %s", exc)


def _send_sns(topic_arn: str, payload: dict[str, Any]) -> None:
    try:
        import boto3
    except ImportError:
        logger.info("boto3 is not installed, SNS delivery skipped")
        return
    try:
        client = boto3.client("sns", region_name=os.getenv("AWS_REGION", "ap-south-1"))
        client.publish(
            TopicArn=topic_arn,
            Subject=f"CrateWatch {payload['severity']} {payload['crate_id']}",
            Message=json.dumps(payload, indent=2),
        )
    except Exception as exc:
        logger.warning("SNS delivery failed: %s", exc)


def notify_incident(incident: dict[str, Any], settings: Settings) -> None:
    payload = {
        "event": "incident_opened",
        "incident_id": incident["id"],
        "crate_id": incident["crate_id"],
        "severity": incident["severity"],
        "rule_id": incident["rule_id"],
        "title": incident["title"],
        "event_ts": incident.get("event_ts"),
        "detected_at": incident["detected_at"],
        "breach_value": incident.get("breach_value"),
        "threshold": incident.get("threshold"),
        "shipment_id": settings.shipment_id,
    }
    logger.warning(json.dumps(payload))

    if settings.alert_webhook_url:
        threading.Thread(
            target=_send_webhook,
            args=(settings.alert_webhook_url, payload),
            daemon=True,
        ).start()

    if settings.alert_sns_topic_arn:
        threading.Thread(
            target=_send_sns,
            args=(settings.alert_sns_topic_arn, payload),
            daemon=True,
        ).start()
