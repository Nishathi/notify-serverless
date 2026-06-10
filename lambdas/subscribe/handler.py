import json
import os
import boto3
from datetime import datetime, timezone
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["SUBSCRIPTIONS_TABLE"])


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


@logger.inject_lambda_context(correlation_id_path="requestContext.requestId")
def handler(event: dict, context: LambdaContext) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
        user_id = body.get("user_id", "").strip()
        topic = body.get("topic", "").strip()

        if not user_id or not topic:
            return _response(400, {"error": "user_id and topic are required"})

        now = datetime.now(timezone.utc).isoformat()
        table.put_item(
            Item={
                "pk": f"TOPIC#{topic}",
                "sk": f"USER#{user_id}",
                "user_id": user_id,
                "topic": topic,
                "subscribed_at": now,
                "ttl": int(datetime.now(timezone.utc).timestamp()) + 86400 * 30,
            }
        )

        logger.info("Subscription created", extra={"user_id": user_id, "topic": topic})
        return _response(201, {"message": "subscribed", "user_id": user_id, "topic": topic})

    except Exception as exc:
        logger.exception("Subscribe failed")
        return _response(500, {"error": str(exc)})
