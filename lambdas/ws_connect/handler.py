import os
import boto3
from datetime import datetime, timezone
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["CONNECTIONS_TABLE"])


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    connection_id = event["requestContext"]["connectionId"]
    user_id = (event.get("queryStringParameters") or {}).get("user_id", "").strip()

    if not user_id:
        return {"statusCode": 400, "body": "user_id query param required"}

    now = datetime.now(timezone.utc).isoformat()
    table.put_item(
        Item={
            "pk": f"USER#{user_id}",
            "sk": connection_id,
            "connection_id": connection_id,
            "user_id": user_id,
            "connected_at": now,
            "ttl": int(datetime.now(timezone.utc).timestamp()) + 3600 * 24,
        }
    )

    logger.info("WS connected", extra={"connection_id": connection_id, "user_id": user_id})
    return {"statusCode": 200}
