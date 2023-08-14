import functools
import json
import os
import subprocess

import boto3

from _nebari import constants
from _nebari.provider.cloud.commons import filter_by_highest_supported_k8s_version


def check_credentials():
    for variable in {
        "AWS_DEFAULT_REGION",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    }:
        if variable not in os.environ:
            raise ValueError(
                f"""Missing the following required environment variable: {variable}\n
                Please see the documentation for more information: {constants.AWS_ENV_DOCS}"""
            )


@functools.lru_cache()
def regions():
    output = subprocess.check_output(["aws", "ec2", "describe-regions"])
    data = json.loads(output.decode("utf-8"))
    return {_["RegionName"]: _["RegionName"] for _ in data["Regions"]}


@functools.lru_cache()
def zones(region: str = "us-west-2"):
    output = subprocess.check_output(
        ["aws", "ec2", "describe-availability-zones", "--region", region]
    )
    data = json.loads(output.decode("utf-8"))
    return {_["ZoneName"]: _["ZoneName"] for _ in data["AvailabilityZones"]}


@functools.lru_cache()
def kubernetes_versions(region="us-west-2"):
    """Return list of available kubernetes supported by cloud provider. Sorted from oldest to latest."""
    # AWS SDK (boto3) currently doesn't offer an intuitive way to list available kubernetes version. This implementation grabs kubernetes versions for specific EKS addons. It will therefore always be (at the very least) a subset of all kubernetes versions still supported by AWS.
    if not os.getenv("AWS_DEFAULT_REGION"):
        os.environ["AWS_DEFAULT_REGION"] = region

    client = boto3.client("eks")
    supported_kubernetes_versions = list()
    available_addons = client.describe_addon_versions()
    for addon in available_addons.get("addons", None):
        for eksbuild in addon.get("addonVersions", None):
            for k8sversion in eksbuild.get("compatibilities", None):
                supported_kubernetes_versions.append(
                    k8sversion.get("clusterVersion", None)
                )

    supported_kubernetes_versions = sorted(list(set(supported_kubernetes_versions)))
    return filter_by_highest_supported_k8s_version(supported_kubernetes_versions)


@functools.lru_cache()
def instances(region: str = "us-west-2"):
    output = subprocess.check_output(
        ["aws", "ec2", "describe-instance-types", "--region", region]
    )
    data = json.loads(output.decode("utf-8"))
    return {_["InstanceType"]: _["InstanceType"] for _ in data["InstanceTypes"]}