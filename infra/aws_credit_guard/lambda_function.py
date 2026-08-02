from __future__ import annotations

import os

import boto3
from botocore.exceptions import ClientError


INSTANCE_NOT_FOUND = {
    "NotFoundException",
    "ResourceNotFoundException",
}


def _missing(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in INSTANCE_NOT_FOUND


def _delete_backend(lightsail, instance_name: str, static_ip_name: str) -> list[str]:
    actions: list[str] = []
    try:
        static_ip = lightsail.get_static_ip(staticIpName=static_ip_name)["staticIp"]
        if static_ip.get("isAttached"):
            lightsail.detach_static_ip(staticIpName=static_ip_name)
            actions.append("static_ip_detached")
    except ClientError as exc:
        if not _missing(exc):
            raise

    try:
        lightsail.delete_instance(
            instanceName=instance_name,
            forceDeleteAddOns=True,
        )
        actions.append("instance_deleted")
    except ClientError as exc:
        if not _missing(exc):
            raise

    try:
        lightsail.release_static_ip(staticIpName=static_ip_name)
        actions.append("static_ip_released")
    except ClientError as exc:
        if not _missing(exc):
            raise
    return actions


def lambda_handler(_event, _context):
    threshold = float(os.environ.get("CREDIT_FLOOR_USD", "30"))
    instance_name = os.environ.get("LIGHTSAIL_INSTANCE_NAME", "max-control-prod")
    static_ip_name = os.environ.get("LIGHTSAIL_STATIC_IP_NAME", "max-control-prod-ip")
    region = os.environ.get("LIGHTSAIL_REGION", "ap-south-1")

    state = boto3.client("freetier", region_name="us-east-1").get_account_plan_state()
    remaining = float(state["accountPlanRemainingCredits"]["amount"])
    actions: list[str] = []
    if remaining <= threshold:
        actions = _delete_backend(
            boto3.client("lightsail", region_name=region),
            instance_name,
            static_ip_name,
        )
    return {
        "remaining_credit_usd": remaining,
        "credit_floor_usd": threshold,
        "actions": actions,
    }
