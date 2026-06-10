import os
import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["CONNECTIONS_TABLE"])


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    connection_id = event["requestContext"]["connectionId"]

    result = table.scan(
        FilterExpression="connection_id = :cid",
        ExpressionAttributeValues={":cid": connection_id},
        ProjectionExpression="pk, sk",
    )
    for item in result.get("Items", []):
        table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})

    logger.info("WS disconnected", extra={"connection_id": connection_id})
    return {"statusCode": 200}
