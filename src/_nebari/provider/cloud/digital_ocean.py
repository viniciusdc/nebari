import functools
import os
import typing

import requests

from _nebari import constants
from _nebari.provider.cloud.commons import filter_by_highest_supported_k8s_version


def check_credentials():
    for variable in {
        "SPACES_ACCESS_KEY_ID",
        "SPACES_SECRET_ACCESS_KEY",
        "DIGITALOCEAN_TOKEN",
    }:
        if variable not in os.environ:
            raise ValueError(
                f"""Missing the following required environment variable: {variable}\n
                Please see the documentation for more information: {constants.DO_ENV_DOCS}"""
            )


def digital_ocean_request(url, method="GET", json=None):
    BASE_DIGITALOCEAN_URL = "https://api.digitalocean.com/v2/"

    for name in {"DIGITALOCEAN_TOKEN"}:
        if name not in os.environ:
            raise ValueError(
                f"Digital Ocean api requests require environment variable={name} defined"
            )

    headers = {"Authorization": f'Bearer {os.environ["DIGITALOCEAN_TOKEN"]}'}

    method_map = {
        "GET": requests.get,
    }

    response = method_map[method](
        f"{BASE_DIGITALOCEAN_URL}{url}", headers=headers, json=json
    )
    response.raise_for_status()
    return response


@functools.lru_cache()
def _kubernetes_options():
    return digital_ocean_request("kubernetes/options").json()


def instances():
    return _kubernetes_options()["options"]["sizes"]


def regions():
    return _kubernetes_options()["options"]["regions"]


def kubernetes_versions(region) -> typing.List[str]:
    """Return list of available kubernetes supported by cloud provider. Sorted from oldest to latest."""
    supported_kubernetes_versions = sorted(
        [_["slug"].split("-")[0] for _ in _kubernetes_options()["options"]["versions"]]
    )
    filtered_versions = filter_by_highest_supported_k8s_version(
        supported_kubernetes_versions
    )
    return [f"{v}-do.0" for v in filtered_versions]