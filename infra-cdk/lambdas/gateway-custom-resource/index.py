# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Custom Resource Lambda for AgentCore Gateway Management

This Lambda function serves as a CloudFormation custom resource to manage the lifecycle
of AWS Bedrock AgentCore Gateways. It handles the creation, updating, and deletion of
gateways and their associated Lambda targets.

Why this custom resource is needed:
- AWS CDK/CloudFormation doesn't natively support AgentCore Gateway resources yet
- Provides declarative infrastructure management for gateways through CloudFormation
- Handles complex gateway lifecycle operations including target management
- Ensures proper cleanup of gateway resources during stack deletion
- Manages gateway configuration updates without manual intervention

Key responsibilities:
1. Gateway Lifecycle: Creates, updates, and deletes AgentCore Gateways
2. Target Management: Creates and manages Lambda targets for tool execution
3. Authentication Setup: Configures JWT authorization with Cognito integration
4. Parameter Storage: Stores gateway configuration in SSM Parameter Store
5. Error Handling: Provides robust error handling and CloudFormation response management

The custom resource integrates with:
- AWS Bedrock AgentCore Control API for gateway operations
- AWS Cognito for JWT-based authentication
- AWS Lambda for tool execution targets
- AWS SSM Parameter Store for configuration storage
- CloudFormation for infrastructure lifecycle management

Usage:
This Lambda is invoked by CloudFormation during stack operations and should not be
called directly. It responds to CREATE, UPDATE, and DELETE events from CloudFormation.
"""

import json
import logging
import time
from typing import Any, Dict

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

agentcore_client = boto3.client("bedrock-agentcore-control")
ssm_client = boto3.client("ssm")


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for AgentCore Gateway custom resource operations.

    Processes CloudFormation custom resource events (CREATE, UPDATE, DELETE) and
    manages the corresponding AgentCore Gateway lifecycle operations.

    Args:
        event: CloudFormation custom resource event containing request type and properties
        context: Lambda execution context (unused but required by Lambda interface)

    Returns:
        Dict containing CloudFormation response with status and resource data

    Raises:
        Handles all exceptions internally and returns FAILED status to CloudFormation
    """
    logger.info(f"Received event: {json.dumps(event)}")

    request_type = event["RequestType"]
    props = event["ResourceProperties"]

    try:
        if request_type == "Create":
            return create_gateway(event, props)
        elif request_type == "Update":
            return update_gateway(event, props)
        elif request_type == "Delete":
            return delete_gateway(event)
        else:
            raise ValueError(f"Unknown request type: {request_type}")

    except Exception as e:
        logger.error(f"Error handling {request_type}: {str(e)}")
        return send_response(event, "FAILED", str(e))


def create_gateway(event: Dict[str, Any], props: Dict[str, Any]) -> Dict[str, Any]:
    """
    Creates a new AgentCore Gateway with Lambda targets.

    This function handles the CREATE operation for the custom resource. It:
    1. Checks if a gateway with the same name already exists (idempotent operation)
    2. Creates a new gateway with JWT authorization if none exists
    3. Waits for the gateway to become ready
    4. Creates Lambda targets for tool execution
    5. Stores configuration parameters in SSM

    Args:
        event: CloudFormation event data
        props: Resource properties from CloudFormation template

    Returns:
        CloudFormation response with gateway details
    """
    logger.info("Creating AgentCore Gateway...")

    gateway_name = props["GatewayName"]
    lambda_arn = props["LambdaArn"]
    api_spec = json.loads(props["ApiSpec"])
    gateway_role_arn = props["GatewayRoleArn"]

    # Check if gateway already exists
    try:
        gateways = agentcore_client.list_gateways()
        for gw in gateways.get("items", []):
            if gw["name"] == gateway_name:
                logger.info(f"Gateway already exists: {gw['gatewayId']}")
                gateway_id = gw["gatewayId"]
                gateway_details = agentcore_client.get_gateway(
                    gatewayIdentifier=gateway_id
                )
                target_id = create_or_update_target(gateway_id, lambda_arn, api_spec)
                update_ssm_parameters(gateway_details, target_id, props)

                # Extract gateway URL - construct if not provided
                gateway_url = gateway_details.get("gatewayUrl")
                if not gateway_url:
                    logger.warning(
                        "Gateway URL not in response, constructing from gateway ID"
                    )
                    gateway_url = f"https://{gateway_id}.gateway.bedrock-agentcore.{props['Region']}.amazonaws.com/mcp"

                return send_response(
                    event,
                    "SUCCESS",
                    data={
                        "GatewayId": gateway_id,
                        "GatewayUrl": gateway_url,
                        "TargetId": target_id,
                    },
                    physical_resource_id=gateway_id,
                )
    except Exception as e:
        logger.warning(f"Error checking existing gateways: {e}")

    # Create new gateway
    auth_config = {
        "customJWTAuthorizer": {
            "allowedClients": [props["CognitoClientId"]],
            "discoveryUrl": props["CognitoDiscoveryUrl"],
        }
    }

    response = agentcore_client.create_gateway(
        name=gateway_name,
        description="GASP Gateway (CDK Managed)",
        roleArn=gateway_role_arn,
        protocolType="MCP",
        authorizerType="CUSTOM_JWT",
        authorizerConfiguration=auth_config,
    )

    gateway_id = response["gatewayId"]
    logger.info(f"Gateway created: {gateway_id}")

    wait_for_gateway_ready(gateway_id)
    gateway_details = agentcore_client.get_gateway(gatewayIdentifier=gateway_id)
    target_id = create_target_with_retry(gateway_id, lambda_arn, api_spec)
    update_ssm_parameters(gateway_details, target_id, props)

    # Extract gateway URL - construct if not provided
    gateway_url = gateway_details.get("gatewayUrl")
    if not gateway_url:
        logger.warning("Gateway URL not in response, constructing from gateway ID")
        gateway_url = f"https://{gateway_id}.gateway.bedrock-agentcore.{props['Region']}.amazonaws.com/mcp"

    logger.info(f"Gateway URL: {gateway_url}")

    return send_response(
        event,
        "SUCCESS",
        data={
            "GatewayId": gateway_id,
            "GatewayUrl": gateway_url,
            "TargetId": target_id,
        },
        physical_resource_id=gateway_id,
    )


def update_gateway(event: Dict[str, Any], props: Dict[str, Any]) -> Dict[str, Any]:
    """
    Updates an existing AgentCore Gateway configuration.

    Handles UPDATE operations by:
    1. Checking if gateway name changed (requires recreation)
    2. Updating Lambda targets with new configuration
    3. Refreshing SSM parameters with updated values

    Args:
        event: CloudFormation event data with old and new properties
        props: New resource properties from CloudFormation template

    Returns:
        CloudFormation response with updated gateway details
    """
    gateway_id = event["PhysicalResourceId"]
    lambda_arn = props["LambdaArn"]
    api_spec = json.loads(props["ApiSpec"])
    old_props = event.get("OldResourceProperties", {})

    # If Gateway name changed, delete old and create new
    if old_props.get("GatewayName") != props.get("GatewayName"):
        logger.info("Gateway name changed, recreating...")
        delete_gateway(event)
        return create_gateway(event, props)

    target_id = create_or_update_target(gateway_id, lambda_arn, api_spec)
    gateway_details = agentcore_client.get_gateway(gatewayIdentifier=gateway_id)
    update_ssm_parameters(gateway_details, target_id, props)

    # Extract gateway URL - construct if not provided
    gateway_url = gateway_details.get("gatewayUrl")
    if not gateway_url:
        logger.warning("Gateway URL not in response, constructing from gateway ID")
        gateway_url = f"https://{gateway_id}.gateway.bedrock-agentcore.{props['Region']}.amazonaws.com/mcp"

    return send_response(
        event,
        "SUCCESS",
        data={
            "GatewayId": gateway_id,
            "GatewayUrl": gateway_url,
            "TargetId": target_id,
        },
        physical_resource_id=gateway_id,
    )


def delete_gateway(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deletes an AgentCore Gateway and all associated resources.

    Handles DELETE operations by:
    1. Deleting all Lambda targets associated with the gateway
    2. Deleting the gateway itself
    3. Gracefully handling cases where resources may already be deleted

    Args:
        event: CloudFormation event data containing gateway ID

    Returns:
        CloudFormation response indicating successful deletion
    """
    gateway_id = event["PhysicalResourceId"]

    try:
        # Delete targets first
        targets = agentcore_client.list_gateway_targets(gatewayIdentifier=gateway_id)
        for target in targets.get("items", []):
            agentcore_client.delete_gateway_target(
                gatewayIdentifier=gateway_id, targetId=target["targetId"]
            )
            time.sleep(5)

        agentcore_client.delete_gateway(gatewayIdentifier=gateway_id)
    except Exception as e:
        logger.warning(f"Error deleting gateway: {e}")

    return send_response(event, "SUCCESS", physical_resource_id=gateway_id)


def create_target_with_retry(
    gateway_id: str, lambda_arn: str, api_spec: list, max_retries: int = 5
) -> str:
    """
    Creates a Lambda target for the gateway with retry logic.

    Lambda targets define how the gateway routes tool calls to specific Lambda functions.
    This function implements exponential backoff retry logic to handle cases where
    the gateway is still in a transitional state.

    Args:
        gateway_id: The AgentCore Gateway identifier
        lambda_arn: ARN of the Lambda function to target
        api_spec: Tool specification defining available tools and their schemas
        max_retries: Maximum number of retry attempts

    Returns:
        Target ID of the created Lambda target

    Raises:
        Exception: If target creation fails after all retry attempts
    """
    for attempt in range(max_retries):
        try:
            response = agentcore_client.create_gateway_target(
                gatewayIdentifier=gateway_id,
                name="GASPAgent",
                description="GASP Agent Lambda Target",
                targetConfiguration={
                    "mcp": {
                        "lambda": {
                            "lambdaArn": lambda_arn,
                            "toolSchema": {"inlinePayload": api_spec},
                        }
                    }
                },
                credentialProviderConfigurations=[
                    {"credentialProviderType": "GATEWAY_IAM_ROLE"}
                ],
            )
            return response["targetId"]

        except Exception as e:
            if "CREATING" in str(e) or "UPDATING" in str(e):
                wait_time = 2**attempt
                logger.info(f"Gateway not ready, waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise

    raise Exception(f"Failed to create target after {max_retries} attempts")


def create_or_update_target(gateway_id: str, lambda_arn: str, api_spec: list) -> str:
    """
    Creates a new Lambda target or updates an existing one.

    This function provides idempotent target management by:
    1. Checking if targets already exist for the gateway
    2. Updating existing targets with new configuration
    3. Creating new targets if none exist

    Args:
        gateway_id: The AgentCore Gateway identifier
        lambda_arn: ARN of the Lambda function to target
        api_spec: Tool specification defining available tools and their schemas

    Returns:
        Target ID of the created or updated Lambda target
    """
    try:
        targets = agentcore_client.list_gateway_targets(gatewayIdentifier=gateway_id)
        if targets.get("items"):
            target_id = targets["items"][0]["targetId"]
            agentcore_client.update_gateway_target(
                gatewayIdentifier=gateway_id,
                targetId=target_id,
                name="GASPAgent",
                targetConfiguration={
                    "mcp": {
                        "lambda": {
                            "lambdaArn": lambda_arn,
                            "toolSchema": {"inlinePayload": api_spec},
                        }
                    }
                },
                credentialProviderConfigurations=[
                    {"credentialProviderType": "GATEWAY_IAM_ROLE"}
                ],
            )
            return target_id
    except Exception as e:
        logger.warning(f"Error checking/updating target: {e}")

    return create_target_with_retry(gateway_id, lambda_arn, api_spec)


def wait_for_gateway_ready(gateway_id: str, max_wait: int = 120) -> None:
    """
    Waits for the gateway to reach READY status before proceeding.

    AgentCore Gateways go through various states during creation. This function
    polls the gateway status until it's ready for target creation or fails.

    Args:
        gateway_id: The AgentCore Gateway identifier
        max_wait: Maximum time to wait in seconds

    Raises:
        Exception: If gateway doesn't become ready within the timeout period
                  or enters a failed state
    """
    start_time = time.time()
    while time.time() - start_time < max_wait:
        response = agentcore_client.get_gateway(gatewayIdentifier=gateway_id)
        status = response["status"]

        if status == "READY":
            return
        elif status in ["FAILED", "DELETING"]:
            raise Exception(f"Gateway in unexpected status: {status}")

        time.sleep(10)

    raise Exception(f"Gateway not ready after {max_wait}s")


def update_ssm_parameters(
    gateway_details: Dict[str, Any], target_id: str, props: Dict[str, Any]
) -> None:
    """
    Stores gateway configuration in SSM Parameter Store for access by other components.

    This function persists gateway configuration that other parts of the system need,
    such as the frontend for API calls and the runtime for tool execution.

    Args:
        gateway_details: Gateway information from AgentCore API
        target_id: Lambda target identifier
        props: Resource properties containing SSM prefix and other config
    """
    ssm_prefix = props["SsmPrefix"]

    gateway_url = gateway_details.get("gatewayUrl")
    if gateway_url:
        ssm_client.put_parameter(
            Name=f"{ssm_prefix}/gateway_url",
            Value=gateway_url,
            Type="String",
            Overwrite=True,
        )

    ssm_client.put_parameter(
        Name=f"{ssm_prefix}/target_id", Value=target_id, Type="String", Overwrite=True
    )

    ssm_client.put_parameter(
        Name=f"{ssm_prefix}/gateway_id",
        Value=gateway_details["gatewayId"],
        Type="String",
        Overwrite=True,
    )


def send_response(
    event: Dict[str, Any],
    status: str,
    reason: str = None,
    data: Dict[str, Any] = None,
    physical_resource_id: str = None,
) -> Dict[str, Any]:
    """
    Sends response back to CloudFormation to complete the custom resource operation.

    This function is required for all CloudFormation custom resources to signal
    completion status back to CloudFormation, allowing the stack operation to proceed.

    Args:
        event: Original CloudFormation event
        status: SUCCESS or FAILED
        reason: Optional reason for the status
        data: Optional data to return to CloudFormation
        physical_resource_id: Unique identifier for the resource

    Returns:
        Response body that was sent to CloudFormation
    """
    import urllib3

    response_body = {
        "Status": status,
        "Reason": reason or f"{status}: See CloudWatch logs",
        "PhysicalResourceId": physical_resource_id
        or event.get("PhysicalResourceId", "NONE"),
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data or {},
    }

    logger.info(f"Sending response: {json.dumps(response_body)}")

    http = urllib3.PoolManager()
    http.request(
        "PUT",
        event["ResponseURL"],
        body=json.dumps(response_body).encode("utf-8"),
        headers={"Content-Type": ""},
    )

    return response_body
