from aws_cdk import (
    Stack, Duration, RemovalPolicy, CfnOutput,
    aws_dynamodb as ddb,
    aws_lambda as _lambda,
    aws_lambda_event_sources as sources,
    aws_sns as sns,
    aws_sns_subscriptions as subs,
    aws_sqs as sqs,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations,
)
from constructs import Construct

POWERTOOLS_LAYER = "arn:aws:lambda:ap-south-1:017000801446:layer:AWSLambdaPowertoolsPythonV2:67"
PYTHON = _lambda.Runtime.PYTHON_3_12
ARM = _lambda.Architecture.ARM_64


def _fn(scope, id_, handler_path: str, env: dict, **kwargs) -> _lambda.Function:
    return _lambda.Function(
        scope, id_,
        runtime=PYTHON,
        architecture=ARM,
        handler="handler.handler",
        code=_lambda.Code.from_asset(handler_path),
        timeout=Duration.seconds(30),
        memory_size=256,
        layers=[_lambda.LayerVersion.from_layer_version_arn(scope, f"{id_}PT", POWERTOOLS_LAYER)],
        environment={"POWERTOOLS_SERVICE_NAME": id_, "LOG_LEVEL": "INFO", **env},
        **kwargs,
    )


class NotificationStack(Stack):
    def __init__(self, scope: Construct, id_: str, **kwargs):
        super().__init__(scope, id_, **kwargs)

        subscriptions = ddb.Table(
            self, "Subscriptions",
            partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="sk", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery=True,
        )

        connections = ddb.Table(
            self, "Connections",
            partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="sk", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        dlq = sqs.Queue(self, "DeliverDLQ", retention_period=Duration.days(7))
        deliver_queue = sqs.Queue(
            self, "DeliverQueue",
            visibility_timeout=Duration.seconds(90),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dlq),
        )

        topic = sns.Topic(self, "NotificationTopic")
        topic.add_subscription(subs.SqsSubscription(deliver_queue))

        http_api = apigwv2.HttpApi(self, "HttpApi",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=["*"],
                allow_methods=[apigwv2.CorsHttpMethod.ANY],
                allow_headers=["*"],
            ),
        )

        subscribe_fn = _fn(self, "Subscribe", "lambdas/subscribe",
            {"SUBSCRIPTIONS_TABLE": subscriptions.table_name})
        publish_fn = _fn(self, "Publish", "lambdas/publish",
            {"SUBSCRIPTIONS_TABLE": subscriptions.table_name,
             "SNS_TOPIC_ARN": topic.topic_arn})

        subscriptions.grant_read_write_data(subscribe_fn)
        subscriptions.grant_read_data(publish_fn)
        topic.grant_publish(publish_fn)

        http_api.add_routes(path="/subscriptions", methods=[apigwv2.HttpMethod.POST],
            integration=integrations.HttpLambdaIntegration("SubInt", subscribe_fn))
        http_api.add_routes(path="/publish", methods=[apigwv2.HttpMethod.POST],
            integration=integrations.HttpLambdaIntegration("PubInt", publish_fn))

        ws_api = apigwv2.WebSocketApi(self, "WsApi")
        ws_stage = apigwv2.WebSocketStage(self, "WsProd",
            web_socket_api=ws_api, stage_name="prod", auto_deploy=True)
        ws_endpoint = f"https://{ws_api.api_id}.execute-api.{self.region}.amazonaws.com/{ws_stage.stage_name}"

        connect_fn = _fn(self, "WsConnect", "lambdas/ws_connect",
            {"CONNECTIONS_TABLE": connections.table_name})
        disconnect_fn = _fn(self, "WsDisconnect", "lambdas/ws_disconnect",
            {"CONNECTIONS_TABLE": connections.table_name})

        connections.grant_read_write_data(connect_fn)
        connections.grant_read_write_data(disconnect_fn)

        ws_api.add_route("$connect",
            integration=integrations.WebSocketLambdaIntegration("ConnInt", connect_fn))
        ws_api.add_route("$disconnect",
            integration=integrations.WebSocketLambdaIntegration("DiscoInt", disconnect_fn))

        deliver_fn = _fn(self, "Deliver", "lambdas/deliver",
            {"CONNECTIONS_TABLE": connections.table_name,
             "APIGW_ENDPOINT": ws_endpoint})

        connections.grant_read_write_data(deliver_fn)
        ws_api.grant_manage_connections(deliver_fn)

        deliver_fn.add_event_source(
            sources.SqsEventSource(deliver_queue, batch_size=10,
                report_batch_item_failures=True))

        CfnOutput(self, "HttpApiUrl", value=http_api.api_endpoint)
        CfnOutput(self, "WsApiUrl", value=f"wss://{ws_api.api_id}.execute-api.{self.region}.amazonaws.com/prod")
