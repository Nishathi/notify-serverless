#!/usr/bin/env python3
import aws_cdk as cdk
from infra.stack import NotificationStack

app = cdk.App()
NotificationStack(app, "NotificationStack",
    env=cdk.Environment(region="ap-south-1"))
app.synth()
