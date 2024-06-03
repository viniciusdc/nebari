import contextlib
import inspect
import os
import pathlib
import re
import sys
import tempfile
from inspect import cleandoc
from typing import Annotated, Any, Dict, List, Optional, Tuple, Type, Union

from pydantic import Field, field_validator, model_validator

from _nebari import constants
from _nebari.provider import terraform
from _nebari.provider.cloud import (
    amazon_web_services,
    azure_cloud,
    digital_ocean,
    google_cloud,
)
from _nebari.stages.base import NebariTerraformStage
from _nebari.stages.tf_objects import NebariTerraformState
from _nebari.utils import (
    AZURE_NODE_RESOURCE_GROUP_SUFFIX,
    construct_azure_resource_group_name,
    modified_environ,
)
from nebari import schema
from nebari.hookspecs import NebariStage, hookimpl


def get_kubeconfig_filename():
    return str(pathlib.Path(tempfile.gettempdir()) / "NEBARI_KUBECONFIG")


class LocalInputVars(schema.Base):
    kubeconfig_filename: str = get_kubeconfig_filename()
    kube_context: Optional[str] = None


class ExistingInputVars(schema.Base):
    kube_context: str


class DigitalOceanNodeGroup(schema.Base):
    instance: str
    min_nodes: int
    max_nodes: int


class DigitalOceanInputVars(schema.Base):
    name: str
    environment: str
    region: str
    tags: List[str]
    kubernetes_version: str
    node_groups: Dict[str, DigitalOceanNodeGroup]
    kubeconfig_filename: str = get_kubeconfig_filename()


class GCPNodeGroupInputVars(schema.Base):
    name: str
    instance_type: str
    min_size: int
    max_size: int
    labels: Dict[str, str]
    preemptible: bool
    guest_accelerators: List["GCPGuestAccelerator"]


class GCPPrivateClusterConfig(schema.Base):
    enable_private_nodes: bool
    enable_private_endpoint: bool
    master_ipv4_cidr_block: str


class GCPInputVars(schema.Base):
    name: str
    environment: str
    region: str
    project_id: str
    availability_zones: List[str]
    node_groups: List[GCPNodeGroupInputVars]
    kubeconfig_filename: str = get_kubeconfig_filename()
    tags: List[str]
    kubernetes_version: str
    release_channel: str
    networking_mode: str
    network: str
    subnetwork: Optional[str] = None
    ip_allocation_policy: Optional[Dict[str, str]] = None
    master_authorized_networks_config: Optional[Dict[str, str]] = None
    private_cluster_config: Optional[GCPPrivateClusterConfig] = None


class AzureNodeGroupInputVars(schema.Base):
    instance: str
    min_nodes: int
    max_nodes: int


class AzureInputVars(schema.Base):
    name: str
    environment: str
    region: str
    kubeconfig_filename: str = get_kubeconfig_filename()
    kubernetes_version: str
    node_groups: Dict[str, AzureNodeGroupInputVars]
    resource_group_name: str
    node_resource_group_name: str
    vnet_subnet_id: Optional[str] = None
    private_cluster_enabled: bool
    tags: Dict[str, str] = {}
    max_pods: Optional[int] = None
    network_profile: Optional[Dict[str, str]] = None


class AWSNodeGroupInputVars(schema.Base):
    name: str
    instance_type: str
    gpu: bool = False
    min_size: int
    desired_size: int
    max_size: int
    single_subnet: bool
    permissions_boundary: Optional[str] = None


class AWSInputVars(schema.Base):
    name: str
    environment: str
    existing_security_group_id: Optional[str] = None
    existing_subnet_ids: Optional[List[str]] = None
    region: str
    kubernetes_version: str
    node_groups: List[AWSNodeGroupInputVars]
    availability_zones: List[str]
    vpc_cidr_block: str
    permissions_boundary: Optional[str] = None
    kubeconfig_filename: str = get_kubeconfig_filename()
    tags: Dict[str, str] = {}


def _calculate_asg_node_group_map(config: schema.Main):
    if config.provider == schema.ProviderEnum.aws:
        return amazon_web_services.aws_get_asg_node_group_mapping(
            config.project_name,
            config.namespace,
            config.amazon_web_services.region,
        )
    else:
        return {}


def _calculate_node_groups(config: schema.Main):
    if config.provider == schema.ProviderEnum.aws:
        return {
            group: {"key": "eks.amazonaws.com/nodegroup", "value": group}
            for group in ["general", "user", "worker"]
        }
    elif config.provider == schema.ProviderEnum.gcp:
        return {
            group: {"key": "cloud.google.com/gke-nodepool", "value": group}
            for group in ["general", "user", "worker"]
        }
    elif config.provider == schema.ProviderEnum.azure:
        return {
            group: {"key": "azure-node-pool", "value": group}
            for group in ["general", "user", "worker"]
        }
    elif config.provider == schema.ProviderEnum.do:
        return {
            group: {"key": "doks.digitalocean.com/node-pool", "value": group}
            for group in ["general", "user", "worker"]
        }
    elif config.provider == schema.ProviderEnum.existing:
        return config.existing.node_selectors
    else:
        return config.local.model_dump()["node_selectors"]


def node_groups_to_dict(node_groups):
    return {ng_name: ng.model_dump() for ng_name, ng in node_groups.items()}


@contextlib.contextmanager
def kubernetes_provider_context(kubernetes_credentials: Dict[str, str]):
    credential_mapping = {
        "config_path": "KUBE_CONFIG_PATH",
        "config_context": "KUBE_CTX",
        "username": "KUBE_USER",
        "password": "KUBE_PASSWORD",
        "client_certificate": "KUBE_CLIENT_CERT_DATA",
        "client_key": "KUBE_CLIENT_KEY_DATA",
        "cluster_ca_certificate": "KUBE_CLUSTER_CA_CERT_DATA",
        "host": "KUBE_HOST",
        "token": "KUBE_TOKEN",
    }

    credentials = {
        credential_mapping[k]: v
        for k, v in kubernetes_credentials.items()
        if v is not None
    }
    with modified_environ(**credentials):
        yield


class KeyValueDict(schema.Base):
    key: str
    value: str


class DigitalOceanNodeGroup(schema.Base):
    """Representation of a node group with Digital Ocean

    - Kubernetes limits: https://docs.digitalocean.com/products/kubernetes/details/limits/
    - Available instance types: https://slugs.do-api.dev/
    """

    instance: str = Field(
        ...,
        description=cleandoc(
            """
            The instance type to use for nodes in this node group. Refer to the Digital
            Ocean instance slugs documentation to choose an appropriate instance type
            based on your needs.
            """
        ),
    )
    min_nodes: Annotated[int, Field(ge=1)] = Field(
        default=1,
        description=cleandoc(
            """
            The minimum number of nodes in this node group. This helps ensure that your
            cluster scales according to workload demands while maintaining a baseline
            capacity.
            """
        ),
    )
    max_nodes: Annotated[int, Field(ge=1)] = Field(
        default=1,
        description=cleandoc(
            """
            The maximum number of nodes in this node group. This setting limits the
            scaling capability of your cluster to prevent over-provisioning of
            resources.
            """
        ),
    )


DEFAULT_DO_NODE_GROUPS = {
    "general": DigitalOceanNodeGroup(instance="g-8vcpu-32gb", min_nodes=1, max_nodes=1),
    "user": DigitalOceanNodeGroup(instance="g-4vcpu-16gb", min_nodes=1, max_nodes=5),
    "worker": DigitalOceanNodeGroup(instance="g-4vcpu-16gb", min_nodes=1, max_nodes=5),
}


class DigitalOceanProvider(schema.Base):
    region: str = Field(
        ...,
        description=cleandoc(
            """
            The geographical region where your Digital Ocean Kubernetes cluster will be
            deployed. By default, during Nebari initialization, the region is
            automatically set to the current value of `DO_DEFAULT_REGION` constant. For more
            details on its implementation, see the `init.py:check_cloud_provider_region` function.
            """
        ),
        note=cleandoc(
            """
            The available regions can be found at Digital Ocean's [select a
            region](https://www.digitalocean.com/docs/kubernetes/how-to/create-cluster/#select-a-region) page.
            keep in mind that changin regions may affect the latency of your services.
            """
        ),
        warning=cleandoc(
            """In case of Nebari been already deployed, if triggered, nebari will
            attempt to create a new cluster in the new region and conflicts may arise.
            """
        ),
    )
    kubernetes_version: Optional[str] = Field(
        None,
        description=cleandoc(
            """
            The specific version of Kubernetes to use for your cluster. Leaving this field
            as None will use the latest version supported by Digital Ocean.

            By default, Nebari will run a check during initiation for all the
            available supported versions of kubernetes in the selected region and will
            use the latest version available. General implementation details can be
            found in the
            [initialize.py](https://github.com/nebari-dev/nebari/blob/develop/src/_nebari/initialize.py#L120-L133) file.
            """
        ),
    )
    node_groups: Dict[str, DigitalOceanNodeGroup] = Field(
        default=DEFAULT_DO_NODE_GROUPS,
        description=cleandoc(
            f"""
            A mapping of node group names to their configurations. Each node group can
            be configured with different instance types and scaling settings based on
            the roles and demands of your applications.
            """
        ),
    )
    tags: Optional[List[str]] = Field(
        default=[],
        description=cleandoc(
            """
            Tags to apply to the resources within the cluster. Tags can help you organize
            and manage your Digital Ocean resources by grouping and filtering them based on
            custom labels.
            """
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _check_input(cls, data: Any) -> Any:
        digital_ocean.check_credentials()

        # check if region is valid
        available_regions = set(_["slug"] for _ in digital_ocean.regions())
        if data["region"] not in available_regions:
            raise ValueError(
                f"Digital Ocean region={data['region']} is not one of {available_regions}"
            )

        # check if kubernetes version is valid
        available_kubernetes_versions = digital_ocean.kubernetes_versions()
        if len(available_kubernetes_versions) == 0:
            raise ValueError(
                "Request to Digital Ocean for available Kubernetes versions failed."
            )
        if data["kubernetes_version"] is None:
            data["kubernetes_version"] = available_kubernetes_versions[-1]
        elif data["kubernetes_version"] not in available_kubernetes_versions:
            raise ValueError(
                f"\nInvalid `kubernetes-version` provided: {data['kubernetes_version']}.\nPlease select from one of the following supported Kubernetes versions: {available_kubernetes_versions} or omit flag to use latest Kubernetes version available."
            )

        available_instances = {_["slug"] for _ in digital_ocean.instances()}
        if "node_groups" in data:
            for _, node_group in data["node_groups"].items():
                if node_group["instance"] not in available_instances:
                    raise ValueError(
                        f"Digital Ocean instance {node_group.instance} not one of available instance types={available_instances}"
                    )
        return data


class GCPIPAllocationPolicy(schema.Base):
    cluster_secondary_range_name: str = Field(
        ...,
        description=cleandoc(
            """
            The name of the secondary range to use for pods in the Kubernetes cluster. The
            secondary range is used to assign IP addresses to pods running on the cluster's
            nodes.
            """
        ),
    )
    services_secondary_range_name: str = Field(
        ...,
        description=cleandoc(
            """
            The name of the secondary range to use for services in the Kubernetes
            cluster.
            """
        ),
    )
    cluster_ipv4_cidr_block: str = Field(
        ...,
        description=cleandoc(
            """
            The IP address range to use for pods in the Kubernetes cluster. The IP
            address range is used to assign IP addresses to pods running on the
            cluster's nodes.
            """
        ),
    )
    services_ipv4_cidr_block: str = Field(
        ...,
        description=cleandoc(
            """
            The IP address range to use for services in the Kubernetes cluster. The IP
            address range is used to assign IP addresses to services running on the
            cluster. The IP address range must be a subset of the VPC network's IP
            address range.
            """
        ),
    )


class GCPCIDRBlock(schema.Base):
    cidr_block: str = Field(
        ...,
        description=cleandoc(
            """
            The IP address range to allow access to the Kubernetes cluster's API server.
            The IP address range must be a valid CIDR block.
            """
        ),
    )
    display_name: str = Field(
        ...,
        description=cleandoc(
            """
            The display name for the CIDR block. The display name is used to identify
            the CIDR block in the Kubernetes cluster's master authorized networks
            configuration.
            """
        ),
    )


class GCPMasterAuthorizedNetworksConfig(schema.Base):
    cidr_blocks: List[GCPCIDRBlock] = Field(
        ...,
        description=cleandoc(
            """
            The list of CIDR blocks to allow access to the Kubernetes cluster's API
            server. Each CIDR block must be a valid CIDR block.
            """
        ),
    )


class GCPPrivateClusterConfig(schema.Base):
    enable_private_endpoint: bool = Field(
        ...,
        description=cleandoc(
            """
            Determines whether to enable a private endpoint for the Kubernetes cluster's
            API server. A private endpoint restricts access to the API server to only
            private IP addresses.
            """
        ),
    )
    enable_private_nodes: bool = Field(
        ...,
        description=cleandoc(
            """
            Determines whether to enable private nodes for the Kubernetes cluster.
            Private nodes restrict access to the cluster's nodes to only private IP
            addresses.
            """
        ),
    )
    master_ipv4_cidr_block: str = Field(
        ...,
        description=cleandoc(
            """
            The IP address range to use for the Kubernetes cluster's master nodes. The
            IP address range is used to assign IP addresses to the cluster's master
            nodes. The IP address range must be a valid CIDR block.
            """
        ),
    )


class GCPGuestAccelerator(schema.Base):
    """
    See general information regarding GPU support at:
    # TODO: replace with nebari.dev new URL
    https://docs.nebari.dev/en/stable/source/admin_guide/gpu.html?#add-gpu-node-group
    """

    name: str = Field(
        ...,
        description=cleandoc(
            """
            The name of the accelerator to use for nodes in this node group. The name
            must be a valid accelerator type supported by Google Cloud.
            """
        ),
    )
    count: Annotated[int, Field(ge=1)] = Field(
        1,
        description=cleandoc(
            """
            The number of accelerators to attach to nodes in this node group. The count
            must be a positive integer.
            """
        ),
    )


class GCPNodeGroup(schema.Base):
    instance: str = Field(
        ...,
        description=cleandoc(
            """
            The instance type to use for nodes in this node group. Refer to the Google
            Cloud instance types documentation to choose an appropriate instance type
            based on your needs.
            """
        ),
    )
    min_nodes: Annotated[int, Field(ge=0)] = Field(
        0,
        description=cleandoc(
            """
            The minimum number of nodes in this node group. This helps ensure that your
            cluster scales according to workload demands while maintaining a baseline
            capacity.
            """
        ),
    )
    max_nodes: Annotated[int, Field(ge=1)] = Field(
        1,
        description=cleandoc(
            """
            The maximum number of nodes in this node group. This setting limits the
            scaling capability of your cluster to prevent over-provisioning of resources.
            """
        ),
    )
    preemptible: bool = Field(
        False,
        description=cleandoc(
            """
            Determines whether to use preemptible VM instances for nodes in this node
            group. Preemptible VM instances are short-lived instances that are cheaper
            than regular instances but can be terminated at any time.
            """
        ),
    )
    labels: Dict[str, str] = Field(
        {},
        description=cleandoc(
            """
            A mapping of labels to apply to nodes in this node group. Labels can help
            you organize and manage your Google Cloud resources by grouping and
            filtering them based on custom labels.
            """
        ),
    )
    guest_accelerators: List[GCPGuestAccelerator] = Field(
        [],
        description=cleandoc(
            """
            A list of guest accelerators to attach to nodes in this node group. Guest
            accelerators are specialized hardware devices that can be attached to nodes
            to improve performance for specific workloads.
            """
        ),
    )


DEFAULT_GCP_NODE_GROUPS = {
    "general": GCPNodeGroup(instance="n1-standard-8", min_nodes=1, max_nodes=1),
    "user": GCPNodeGroup(instance="n1-standard-4", min_nodes=0, max_nodes=5),
    "worker": GCPNodeGroup(instance="n1-standard-4", min_nodes=0, max_nodes=5),
}


class GoogleCloudPlatformProvider(schema.Base):
    region: str = Field(
        ...,
        description=cleandoc(
            """
            The geographical region where your Google Cloud Kubernetes cluster will be
            deployed. By default, during Nebari initialization, the region is
            automatically set to the current value of `GCP_DEFAULT_REGION` constant. For more
            details on its implementation, see the `init.py:check_cloud_provider_region` function.
            """
        ),
        note=cleandoc(
            """
            The available regions can be found at Google Cloud's [select a
            region](https://cloud.google.com/compute/docs/regions-zones) page.
            keep in mind that changing regions may affect the latency of your services.
            """
        ),
        warning=cleandoc(
            """In case of Nebari have been already deployed, if triggered, it will
            attempt to create a new cluster in the new region and conflicts may arise.
            """
        ),
    )
    project: str = Field(
        ...,
        description=cleandoc(
            """
            The name of the Google Cloud project to use for the Kubernetes cluster. The
            project is used to group and manage resources within Google Cloud.
            """
        ),
    )
    kubernetes_version: str = Field(
        None,
        description=cleandoc(
            """
            The specific version of Kubernetes to use for your cluster. Leaving this field
            as None will use the latest version supported by Google Cloud.

            By default, Nebari will run a check during initiation for all the
            available supported versions of kubernetes in the selected region and will
            use the latest version available. General implementation details can be
            found in the
            [initialize.py]
            """
        ),
    )
    availability_zones: Optional[List[str]] = Field(
        [],
        description=cleandoc(
            """
            The availability zones to use for the Kubernetes cluster. Availability zones
            are distinct locations within a region that are isolated from each other to
            protect against failures in one zone affecting the others.
            """
        ),
    )
    release_channel: str = Field(
        constants.DEFAULT_GKE_RELEASE_CHANNEL,
        description=cleandoc(
            """
            The release channel to use for the Kubernetes cluster. The release channel
            determines how quickly new versions of Kubernetes are made available to your
            cluster.
            """
        ),
    )
    node_groups: Dict[str, GCPNodeGroup] = Field(
        DEFAULT_GCP_NODE_GROUPS,
        description=cleandoc(
            """
            A mapping of node group names to their configurations. Each node group can
            be configured with different instance types and scaling settings based on
            the roles and demands of your applications.
            """
        ),
    )
    tags: Optional[List[str]] = Field(
        [],
        description=cleandoc(
            """
            Tags to apply to the resources within the cluster. Tags can help you organize
            and manage your Google Cloud resources by grouping and filtering them based on
            custom labels.
            """
        ),
    )
    networking_mode: str = Field(
        "ROUTE",
        description=cleandoc(
            """
            The networking mode to use for the Kubernetes cluster. The networking mode
            determines how the cluster's nodes communicate with each other and with the
            outside world.
            """
        ),
    )
    network: str = Field(
        "default",
        description=cleandoc(
            """
            The name of the network to use for the Kubernetes cluster. The network is used
            to define the IP address range and subnetworks that the cluster's nodes will use.
            """
        ),
    )
    subnetwork: Optional[Union[str, None]] = Field(
        None,
        description=cleandoc(
            """
            The name of the subnetwork to use for the Kubernetes cluster. The subnetwork is
            used to define the IP address range and routing rules for the cluster's nodes.
            """
        ),
    )
    ip_allocation_policy: Optional[Union[GCPIPAllocationPolicy, None]] = Field(
        None,
        description=cleandoc(
            """
            The IP allocation policy to use for the Kubernetes cluster. The IP allocation
            policy determines how IP addresses are assigned to the cluster's nodes and pods.
            """
        ),
    )
    master_authorized_networks_config: Optional[Union[GCPCIDRBlock, None]] = Field(
        None,
        description=cleandoc(
            """
            The master authorized networks configuration to use for the Kubernetes cluster.
            The master authorized networks configuration determines which IP addresses are
            allowed to access the cluster's API server.
            """
        ),
    )
    private_cluster_config: Optional[Union[GCPPrivateClusterConfig, None]] = Field(
        None,
        description=cleandoc(
            """
            The private cluster configuration to use for the Kubernetes cluster. The private
            cluster configuration determines whether the cluster's nodes and API server are
            accessible only through private IP addresses.
            """
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _check_input(cls, data: Any) -> Any:
        google_cloud.check_credentials()
        avaliable_regions = google_cloud.regions()
        if data["region"] not in avaliable_regions:
            raise ValueError(
                f"Google Cloud region={data['region']} is not one of {avaliable_regions}"
            )

        available_kubernetes_versions = google_cloud.kubernetes_versions(data["region"])
        print(available_kubernetes_versions)
        if data["kubernetes_version"] not in available_kubernetes_versions:
            raise ValueError(
                f"\nInvalid `kubernetes-version` provided: {data['kubernetes_version']}.\nPlease select from one of the following supported Kubernetes versions: {available_kubernetes_versions} or omit flag to use latest Kubernetes version available."
            )
        return data


class AzureNodeGroup(schema.Base):
    instance: str = Field(
        ...,
        description=cleandoc(
            """
            The instance type to use for nodes in this node group. Refer to the Microsoft
            Azure instance types documentation to choose an appropriate instance type based
            on your needs.
            """
        ),
    )
    min_nodes: int = Field(
        ...,
        description=cleandoc(
            """
            The minimum number of nodes in this node group. This helps ensure that your
            cluster scales according to workload demands while maintaining a baseline
            capacity.
            """
        ),
    )
    max_nodes: int = Field(
        ...,
        description=cleandoc(
            """
            The maximum number of nodes in this node group. This setting limits the
            scaling capability of your cluster to prevent over-provisioning of
            resources.
            """
        ),
    )


DEFAULT_AZURE_NODE_GROUPS = {
    "general": AzureNodeGroup(instance="Standard_D8_v3", min_nodes=1, max_nodes=1),
    "user": AzureNodeGroup(instance="Standard_D4_v3", min_nodes=0, max_nodes=5),
    "worker": AzureNodeGroup(instance="Standard_D4_v3", min_nodes=0, max_nodes=5),
}


class AzureProvider(schema.Base):
    region: str = Field(
        ...,
        description=cleandoc(
            """
            The geographical region where your Microsoft Azure Kubernetes cluster will be
            deployed. By default, during Nebari initialization, the region is
            automatically set to the current value of `AZURE_DEFAULT_REGION` constant. For more
            details on its implementation, see the `init.py:check_cloud_provider_region` function.
            """
        ),
        note=cleandoc(
            """
            The available regions can be found at Microsoft Azure's [select a
            region](https://docs.microsoft.com/en-us/azure/azure-resource-manager/management/manage-resources-portal#select-a-region) page.
            keep in mind that changing regions may affect the latency of your services.
            """
        ),
        warning=cleandoc(
            """In case of Nebari have been already deployed, if triggered, it will
            attempt to create a new cluster in the new region and conflicts may arise.
            """
        ),
    )
    kubernetes_version: Optional[str] = Field(
        None,
        description=cleandoc(
            """
            The specific version of Kubernetes to use for your cluster. Leaving this field
            as None will use the latest version supported by Microsoft Azure.

            By default, Nebari will run a check during initiation for all the
            available supported versions of kubernetes in the selected region and will
            use the latest version available. General implementation details can be
            found in the
            [initialize.py](https://github.com/nebari-dev/nebari/blob/develop/src/_nebari/initialize.py#L120-L133)
            file.
            """
        ),
    )
    storage_account_postfix: str = Field(
        ...,
        description=cleandoc(
            """
            The postfix to use for the storage account name. The storage account is used
            for the Azure Disk and Azure File storage classes.
            """
        ),
    )
    resource_group_name: Optional[str] = Field(
        None,
        description=cleandoc(
            """
            The name of the Azure Resource Group to use for the Kubernetes cluster. If not
            provided, Nebari will automatically generate a name based on the project and
            namespace.
            """
        ),
    )
    node_groups: Dict[str, AzureNodeGroup] = Field(
        default=DEFAULT_AZURE_NODE_GROUPS,
        description=cleandoc(
            """
            A mapping of node group names to their configurations. Each node group can
            be configured with different instance types and scaling settings based on
            the roles and demands of your applications.
            """
        ),
    )
    storage_account_postfix: str = Field(
        ...,
        description=cleandoc(
            """
            The postfix to use for the storage account name. The storage account is used
            for the Azure Disk and Azure File storage classes.
            """
        ),
    )
    vnet_subnet_id: Optional[str] = Field(
        None,
        description=cleandoc(
            """
            The ID of the subnet to use for the Kubernetes cluster. If not provided, Nebari
            will automatically generate a subnet based on the project and namespace.
            """
        ),
    )
    private_cluster_enabled: bool = Field(
        False,
        description=cleandoc(
            """
            Determines whether to enable private cluster mode for the Kubernetes cluster.
            Private cluster mode restricts access to the cluster's API server to only
            private IP addresses.
            """
        ),
    )
    resource_group_name: Optional[str] = Field(
        None,
        description=cleandoc(
            """
            The name of the Azure Resource Group to use for the Kubernetes cluster. If not
            provided, Nebari will automatically generate a name based on the project and
            namespace.
            """
        ),
    )
    tags: Optional[Dict[str, str]] = Field(
        default={},
        description=cleandoc(
            """
            Tags to apply to the resources within the cluster. Tags can help you organize
            and manage your Azure resources by grouping and filtering them based on custom
            labels.
            """
        ),
    )
    network_profile: Optional[Dict[str, str]] = Field(
        None,
        description=cleandoc(
            """
            The network profile to use for the Kubernetes cluster. The network profile
            determines the network configuration for the cluster, including the maximum
            number of pods per node.
            """
        ),
    )
    max_pods: Optional[int] = Field(
        None,
        description=cleandoc(
            """
            The maximum number of pods per node to allow in the Kubernetes cluster. If not
            provided, Nebari will automatically set this value based on the instance type
            of the node group.
            """
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _check_credentials(cls, data: Any) -> Any:
        azure_cloud.check_credentials()
        return data

    @field_validator("kubernetes_version")
    @classmethod
    def _validate_kubernetes_version(cls, value: Optional[str]) -> str:
        available_kubernetes_versions = azure_cloud.kubernetes_versions()
        if value is None:
            value = available_kubernetes_versions[-1]
        elif value not in available_kubernetes_versions:
            raise ValueError(
                f"\nInvalid `kubernetes-version` provided: {value}.\nPlease select from one of the following supported Kubernetes versions: {available_kubernetes_versions} or omit flag to use latest Kubernetes version available."
            )
        return value

    @field_validator("resource_group_name")
    @classmethod
    def _validate_resource_group_name(cls, value):
        if value is None:
            return value
        length = len(value) + len(AZURE_NODE_RESOURCE_GROUP_SUFFIX)
        if length < 1 or length > 90:
            raise ValueError(
                f"Azure Resource Group name must be between 1 and 90 characters long, when combined with the suffix `{AZURE_NODE_RESOURCE_GROUP_SUFFIX}`."
            )
        if not re.match(r"^[\w\-\.\(\)]+$", value):
            raise ValueError(
                "Azure Resource Group name can only contain alphanumerics, underscores, parentheses, hyphens, and periods."
            )
        if value[-1] == ".":
            raise ValueError("Azure Resource Group name can't end with a period.")

        return value

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, value: Optional[Dict[str, str]]) -> Dict[str, str]:
        return value if value is None else azure_cloud.validate_tags(value)


class AWSNodeGroup(schema.Base):
    instance: str = Field(
        ...,
        description=cleandoc(
            """
            The instance type to use for nodes in this node group. Refer to the Amazon
            Web Services instance types documentation to choose an appropriate instance
            type based on your needs.
            """
        ),
    )
    min_nodes: int = Field(
        0,
        description=cleandoc(
            """
            The minimum number of nodes in this node group. This helps ensure that your
            cluster scales according to workload demands while maintaining a baseline
            capacity.
            """
        ),
    )
    max_nodes: int = Field(
        1,
        description=cleandoc(
            """
            The maximum number of nodes in this node group. This setting limits the
            scaling capability of your cluster to prevent over-provisioning of
            resources.
            """
        ),
    )
    gpu: bool = Field(
        False,
        description=cleandoc(
            """
            Determines whether to enable GPU support for nodes in this node group. This
            setting is useful for workloads that require GPU acceleration.
            """
        ),
    )
    single_subnet: bool = Field(
        False,
        description=cleandoc(
            """
            Determines whether to use a single subnet for all nodes in this node group.
            This setting is useful for simplifying network configurations and reducing
            complexity.
            """
        ),
    )
    permissions_boundary: Optional[str] = Field(
        None,
        description=cleandoc(
            """
            The ARN of the permissions boundary to use for the Amazon Web Services
            Kubernetes cluster. By default, Nebari will automatically set this field to
            `None`. For more details on its implementation, see the
            `init.py:check_cloud_provider_region` function.
            """
        ),
    )


DEFAULT_AWS_NODE_GROUPS = {
    "general": AWSNodeGroup(instance="m5.2xlarge", min_nodes=1, max_nodes=1),
    "user": AWSNodeGroup(
        instance="m5.xlarge", min_nodes=0, max_nodes=5, single_subnet=False
    ),
    "worker": AWSNodeGroup(
        instance="m5.xlarge", min_nodes=0, max_nodes=5, single_subnet=False
    ),
}


class AmazonWebServicesProvider(schema.Base):
    region: str = Field(
        ...,
        description=cleandoc(
            """
            The geographical region where your Amazon Web Services Kubernetes cluster
            will be deployed. By default, during Nebari initialization, the region is
            automatically set to the current value of `AWS_DEFAULT_REGION` constant. For more
            details on its implementation, see the `init.py:check_cloud_provider_region` function.
            """
        ),
        note=cleandoc(
            """
            The available regions can be found at Amazon Web Services' [select a
            region](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-regions-availability-zones.html#concepts-available-regions) page.
            keep in mind that changing regions may affect the latency of your services.
            """
        ),
        warning=cleandoc(
            """In case of Nebari have been already deployed, if triggered, it will
            attempt to create a new cluster in the new region and conflicts may arise.
            """
        ),
    )
    kubernetes_version: str = Field(
        None,
        description=cleandoc(
            """
            The specific version of Kubernetes to use for your cluster. Leaving this field
            as None will use the latest version supported by Amazon Web Services.

            By default, Nebari will run a check during initiation for all the
            available supported versions of kubernetes in the selected region and will
            use the latest version available. General implementation details can be
            found in the
            [initialize.py](https://github.com/nebari-dev/nebari/blob/develop/src/_nebari/initialize.py#L120-L133)
            file.
            """
        ),
    )
    availability_zones: Optional[List[str]] = Field(
        default=[],
        description=cleandoc(
            """
            A list of availability zones in which to deploy your EKS cluster. By default, Nebari will automatically set this field to
            the first two availability zones in the selected region.

            If your region of choice was `us-east-1`, the default availability zones
            would be `['us-east-1a', 'us-east-1b']`. Those values are fetched from the
            aws api and are subject to change.
            """
        ),
        note=cleandoc(
            """
            The available availability zones can be found at Amazon Web Services'
            [select a region](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-regions-availability-zones.html#concepts-available-regions)
            page. Keep in mind that different availability zones may have different
            affects on the latency of your services.
            """
        ),
        warning=cleandoc(
            """Do not update this field after the cluster has been created, as it may
            cause issues with the cluster's networking configuration and may lead to a
            complete cluster rebuild.
            """
        ),
    )
    node_groups: Dict[str, AWSNodeGroup] = Field(
        default=DEFAULT_AWS_NODE_GROUPS,
        description=cleandoc(
            """
            A mapping of node group names to their configurations. Each node group can
            be configured with different instance types and scaling settings based on
            the roles and demands of your applications.
            """
        ),
    )
    existing_subnet_ids: Optional[List[str]] = Field(
        default=None,
        description=cleandoc(
            """
            A list of existing subnet IDs to use for the Amazon Web Services Kubernetes
            cluster. By default, Nebari will automatically set this field to `None`. For
            more details on its implementation, see the `init.py:check_cloud_provider_region`
            function.
            """
        ),
    )
    existing_security_group_id: Optional[str] = Field(
        default=None,
        description=cleandoc(
            """
            The ID of an existing security group to use for the Amazon Web Services
            Kubernetes cluster. By default, Nebari will automatically set this field to
            `None`. For more details on its implementation, see the
            `init.py:check_cloud_provider_region` function.
            """
        ),
    )
    vpc_cidr_block: str = Field(
        "10.10.0.0/16",
        description=cleandoc(
            """
            The CIDR block to use for the Amazon Web Services Kubernetes cluster's VPC.
            By default, Nebari will automatically set this field to `"10.10.0.0/16"`.
            For
            more details on its implementation, see the
            `init.py:check_cloud_provider_region`
            function.
            """
        ),
    )
    permissions_boundary: Optional[str] = Field(
        default=None,
        description=cleandoc(
            """
            The ARN of the permissions boundary to use for the Amazon Web Services
            Kubernetes cluster. By default, Nebari will automatically set this field to
            `None`. For more details on its implementation, see the
            `init.py:check_cloud_provider_region` function.
            """
        ),
    )
    tags: Optional[Dict[str, str]] = Field(
        default={},
        description=cleandoc(
            """
            Tags to apply to the resources within the cluster. Tags can help you organize
            and manage your Amazon Web Services resources by grouping and filtering them
            based on custom labels.
            """
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _check_input(cls, data: Any) -> Any:
        amazon_web_services.check_credentials()

        # check if region is valid
        available_regions = amazon_web_services.regions(data["region"])
        if data["region"] not in available_regions:
            raise ValueError(
                f"Amazon Web Services region={data['region']} is not one of {available_regions}"
            )

        # check if kubernetes version is valid
        available_kubernetes_versions = amazon_web_services.kubernetes_versions(
            data["region"]
        )
        if len(available_kubernetes_versions) == 0:
            raise ValueError("Request to AWS for available Kubernetes versions failed.")
        if data["kubernetes_version"] is None:
            data["kubernetes_version"] = available_kubernetes_versions[-1]
        elif data["kubernetes_version"] not in available_kubernetes_versions:
            raise ValueError(
                f"\nInvalid `kubernetes-version` provided: {data['kubernetes_version']}.\nPlease select from one of the following supported Kubernetes versions: {available_kubernetes_versions} or omit flag to use latest Kubernetes version available."
            )

        # check if availability zones are valid
        available_zones = amazon_web_services.zones(data["region"])
        if "availability_zones" not in data:
            data["availability_zones"] = list(sorted(available_zones))[:2]
        else:
            for zone in data["availability_zones"]:
                if zone not in available_zones:
                    raise ValueError(
                        f"Amazon Web Services availability zone={zone} is not one of {available_zones}"
                    )

        # check if instances are valid
        available_instances = amazon_web_services.instances(data["region"])
        if "node_groups" in data:
            for _, node_group in data["node_groups"].items():
                instance = (
                    node_group["instance"]
                    if hasattr(node_group, "__getitem__")
                    else node_group.instance
                )
                if instance not in available_instances:
                    raise ValueError(
                        f"Amazon Web Services instance {node_group.instance} not one of available instance types={available_instances}"
                    )
        return data


class LocalProvider(schema.Base):
    kube_context: Optional[str] = Field(
        default=None,
        description=cleandoc(
            "Optional Kubernetes context specifying which kube-config context to use. Useful when managing multiple clusters. When using alongside Kind, during Nebari's deployment, this will be automatically set to `test-cluster`."
        ),
    )
    node_selectors: Dict[str, KeyValueDict] = Field(
        default={
            "general": KeyValueDict(key="kubernetes.io/os", value="linux"),
            "user": KeyValueDict(key="kubernetes.io/os", value="linux"),
            "worker": KeyValueDict(key="kubernetes.io/os", value="linux"),
        },
        description=cleandoc(
            """
            Node selectors are used to target specific nodes for different workloads.
            Each key represents a node category, and the associated value specifies a
            selector in the form of a `KeyValueDict` object.

            The `kubernetes.io/os` label is used here to ensure pods are scheduled on
            nodes with a matching operating system, when using alongside Kind, this will
            be automatically match the created local nodes.

            Nebari uses these selectors to deploy different components on the cluster
            based on their given categories. By default, Nebari expects the following
            node categories: `general`, `user`, and `worker`.

            Whereas `general` is used for system components, and mainstream services, such
            as Conda-store, Argo, JupyterHub and others. `user` is especificaly used for
            JupyterLab user instances during spawn, and `worker` is used for any other
            service that requires computing power, such as Dask, Argo workflows, etc.
            """
        ),
        examples=[
            cleandoc(
                """
                Besides the defaults nodes, you can add a any other node category by
                adding a new key to the `node_selectors` dictionary. Just be aware, that
                you need to ensure that the label you are using is present in the nodes
                you want to target.

                ```yaml
                node_selectors:
                    ...
                    dashboard:
                        key: "kubernetes.io/os"
                        value: "linux"
                    arm-worker:
                        key: "kubernetes.io/arch"
                        value: "arm64"
                ```
                """
            ),
        ],
    )


class ExistingProvider(schema.Base):
    kube_context: Optional[str] = Field(
        default=None,
        description=cleandoc(
            "Optional Kubernetes context specifying which kube-config context to use. This is extremely useful when deploying to an existing cluster, especially when managing multiple clusters."
        ),
        examples={
            "AWS": cleandoc(
                """
                Bellow is an example of how to set the `kube_context` field in the
                event that you need to specify the correct cluster, when deploying into
                an existing AWS infrastructure:

                ```yaml
                kube_context: arn:aws:eks:<region>:xxxxxxxxxxxx:cluster/
                ```
                """
            ),
            "GCP": cleandoc(
                """
                Bellow is an example of how to set the `kube_context` field in the
                event that you need to specify the correct cluster, when deploying into
                an existing GCP infrastructure:

                ```yaml
                kube_context: gke_<project_id>_<region>_<cluster_name>
                ```
                """
            ),
            "Azure": cleandoc(
                """
                Bellow is an example of how to set the `kube_context` field in the
                event that you need to specify the correct cluster, when deploying into
                an existing Azure infrastructure:

                ```yaml
                kube_context: <cluster_name>
                ```
                """
            ),
            "DO": cleandoc(
                """
                Bellow is an example of how to set the `kube_context` field in the
                event that you need to specify the correct cluster, when deploying into
                an existing Digital Ocean infrastructure:

                ```yaml
                kube_context: <cluster_name>
                ```
                """
            ),
        },
    )
    node_selectors: Dict[str, KeyValueDict] = Field(
        default={
            "general": KeyValueDict(key="kubernetes.io/os", value="linux"),
            "user": KeyValueDict(key="kubernetes.io/os", value="linux"),
            "worker": KeyValueDict(key="kubernetes.io/os", value="linux"),
        },
        description=cleandoc(
            """
            Node selectors in Nebari target specific nodes for various workloads using a
            `KeyValueDict` object for each node category. The system categorizes nodes
            as `general`, `user`, and `worker`:

            - `general`: Deploys system components and mainstream services like
              Conda-store, Argo, and JupyterHub.
            - `user`: Allocates JupyterLab instances to users.
            - `worker`: Handles computing-intensive services such as Dask and Argo
              workflows.

            Adjustments may be necessary for pre-existing clusters to align node
            selectors with current node labels, particularly in cloud environments where
            node pool labels are standard. These labels differ by cloud provider, so
            reviewing the provider's documentation is recommended:
            - Azure: `kubernetes.azure.com/agentpool` ([reserved system labels](https://learn.microsoft.com/en-us/azure/aks/use-labels#reserved-system-labels)).
            - AWS: `eks.amazonaws.com/nodegroup` ([managed node groups behavior](https://docs.aws.amazon.com/eks/latest/userguide/managed-node-update-behavior.html)).
            - GCP: `cloud.google.com/gke-nodepool` ([managing node pools](https://cloud.google.com/kubernetes-engine/docs/how-to/node-pools)).
            - Digital Ocean: `doks.digitalocean.com/node-pool` ([automatic labels
            application](https://docs.digitalocean.com/products/kubernetes/details/managed/#automatic-application-of-labels-to-nodes)).
            """
        ),
        examples={
            "AWS": cleandoc(
                """
                Below is an example of how to set the `node_selectors` field in the
                event that you need to specify the correct node group, when deploying
                into an existing AWS infrastructure. It is of the utmost importance to
                ensure that the node group label you are using (value) matches the
                given node group name in your AWS infrastructure:
                ```yaml
                node_selectors:
                    general:
                        key: "eks.amazonaws.com/nodegroup"
                        value: "general"
                    user:
                        key: "eks.amazonaws.com/nodegroup"
                        value: "user"
                    worker:
                        key: "eks.amazonaws.com/nodegroup"
                        value: "worker"
                    my_custom_node:
                        key: "eks.amazonaws.com/nodegroup"
                        value: "my_custom_node"
                ```
                """
            ),
            "GCP": cleandoc(
                """
                Below is an example of how to set the `node_selectors` field in the
                event that you need to specify the correct node pool, when deploying into
                an existing GCP infrastructure. It is of the utmost importance to ensure
                that the node pool label you are using (value) matches the given node
                pool name in your GCP infrastructure:
                ```yaml
                node_selectors:
                    general:
                        key: "cloud.google.com/gke-nodepool"
                        value: "general"
                    user:
                        key: "cloud.google.com/gke-nodepool"
                        value: "user"
                    worker:
                        key: "cloud.google.com/gke-nodepool"
                        value: "worker"
                    my_custom_node:
                        key: "cloud.google.com/gke-nodepool"
                        value: "my_custom_node"
                ```
                """
            ),
            "Azure": cleandoc(
                """
                Below is an example of how to set the `node_selectors` field in the
                event that you need to specify the correct node pool, when deploying into
                an existing Azure infrastructure. It is of the utmost importance to ensure
                that the node pool label you are using (value) matches the given node pool
                name in your Azure infrastructure:
                ```yaml
                node_selectors:
                    general:
                        key: "kubernetes.azure.com/agentpool"
                        value: "general"
                    user:
                        key: "kubernetes.azure.com/agentpool"
                        value: "user"
                    worker:
                        key: "kubernetes.azure.com/agentpool"
                        value: "worker"
                    my_custom_node:
                        key: "kubernetes.azure.com/agentpool"
                        value: "my_custom_node"
                ```
                """
            ),
            "DO": cleandoc(
                """
                Below is an example of how to set the `node_selectors` field in the
                event that you need to specify the correct node pool, when deploying into
                an existing Digital Ocean infrastructure. It is of the utmost importance to
                ensure that the node pool label you are using (value) matches the given node
                pool name in your Digital Ocean infrastructure:
                ```yaml
                node_selectors:
                    general:
                        key: "doks.digitalocean.com/node-pool"
                        value: "general"
                    user:
                        key: "doks.digitalocean.com/node-pool"
                        value: "user"
                    worker:
                        key: "doks.digitalocean.com/node-pool"
                        value: "worker"
                    my_custom_node:
                        key: "doks.digitalocean.com/node-pool"
                        value: "my_custom_node"
                ```
                """
            ),
        },
    )


provider_enum_model_map = {
    schema.ProviderEnum.local: LocalProvider,
    schema.ProviderEnum.existing: ExistingProvider,
    schema.ProviderEnum.gcp: GoogleCloudPlatformProvider,
    schema.ProviderEnum.aws: AmazonWebServicesProvider,
    schema.ProviderEnum.azure: AzureProvider,
    schema.ProviderEnum.do: DigitalOceanProvider,
}

provider_enum_name_map: Dict[schema.ProviderEnum, str] = {
    schema.ProviderEnum.local: "local",
    schema.ProviderEnum.existing: "existing",
    schema.ProviderEnum.gcp: "google_cloud_platform",
    schema.ProviderEnum.aws: "amazon_web_services",
    schema.ProviderEnum.azure: "azure",
    schema.ProviderEnum.do: "digital_ocean",
}

provider_name_abbreviation_map: Dict[str, str] = {
    value: key.value for key, value in provider_enum_name_map.items()
}
# This is used as part of Upgrade_2024_4_1 when users din't have the corresponding
# provider configuration in their configuration file.
provider_enum_default_node_groups_map: Dict[schema.ProviderEnum, Any] = {
    schema.ProviderEnum.gcp: node_groups_to_dict(DEFAULT_GCP_NODE_GROUPS),
    schema.ProviderEnum.aws: node_groups_to_dict(DEFAULT_AWS_NODE_GROUPS),
    schema.ProviderEnum.azure: node_groups_to_dict(DEFAULT_AZURE_NODE_GROUPS),
    schema.ProviderEnum.do: node_groups_to_dict(DEFAULT_DO_NODE_GROUPS),
}


class InputSchema(schema.Base):
    local: Optional[LocalProvider] = Field(
        default_factory=lambda _: LocalProvider(),
        description=cleandoc(
            """
            Local deployment is intended for Nebari deployments on a `local` cluster
            created and management by [Kind](https://kind.sigs.k8s.io/). It is great for experimentation and
            development.
            """
        ),
        warning=cleandoc(
            """
            Support for local deployments have only been fully tested on Linux based
            systems. MacOS support is currently experimental.
            """
        ),
        depends_on={"provider": schema.ProviderEnum.local},
        examples=[
            cleandoc(
                """Bellow is a full example of how the defaults values are set for the
                local provider:
                ```yaml
                local:
                    kube_context: test-cluster
                    node_selectors:
                        general:
                            key: "kubernetes.io/os"
                            value: "linux"
                        user:
                            key: "kubernetes.io/os"
                            value: "linux"
                        worker:
                            key: "kubernetes.io/os"
                            value: "linux"
                ```
                """
            )
        ],
    )
    existing: Optional[ExistingProvider] = Field(
        default_factory=lambda: ExistingProvider(),
        description=cleandoc(
            """
            Originally designed for Nebari deployments on `local` clusters, this feature
            has since expanded to allow users to deploy Nebari to any
            existing kubernetes cluster. This is useful for deploying Nebari to
            more controlled environments where cluster management is already in place.
            """
        ),
        note=cleandoc(
            """
            By default, Nebari will render the deployment mode similar to how `local`
            works. Which means that, without extra configuration, the deployment of the
            cluster infrastructure will assume the presence a local cluster, already
            created by tools like k3s, Kind or MiniKube, and the default settings for
            both `kube_context` and `node_selector` will be used.
            """
        ),
        depends_on={"provider": schema.ProviderEnum.existing},
        examples={
            "AWS": cleandoc(
                """
                Below is an example of how to set the `kube_context` field in the
                event that you need to specify the correct cluster, when deploying into
                an existing AWS infrastructure:
                ```yaml
                existing:
                    kube_context: arn:aws:eks:<region>:xxxxxxxxxxxx:cluster/
                    node_selectors:
                        general:
                            key: "eks.amazonaws.com/nodegroup"
                            value: "general"
                        user:
                            key: "eks.amazonaws.com/nodegroup"
                            value: "user"
                        worker:
                            key: "eks.amazonaws.com/nodegroup"
                            value: "worker"
                    ```
                """
            ),
            "GCP": cleandoc(
                """
                Below is an example of how to set the `kube_context` field in the
                event that you need to specify the correct cluster, when deploying into
                an existing GCP infrastructure:
                ```yaml
                existing:
                    kube_context: gke_<project_id>_<region>_<cluster_name>
                    node_selectors:
                        general:
                            key: "cloud.google.com/gke-nodepool"
                            value: "general"
                        user:
                            key: "cloud.google.com/gke-nodepool"
                            value: "user"
                        worker:
                            key: "cloud.google.com/gke-nodepool"
                            value: "worker"
                ```
                """
            ),
            "Azure": cleandoc(
                """
                Below is an example of how to set the `kube_context` field in the
                event that you need to specify the correct cluster, when deploying into
                an existing Azure infrastructure:
                ```yaml
                existing:
                    kube_context: <cluster_name>
                    node_selectors:
                        general:
                            key: "kubernetes.azure.com/agentpool"
                            value: "general"
                        user:
                            key: "kubernetes.azure.com/agentpool"
                            value: "user"
                        worker:
                            key: "kubernetes.azure.com/agentpool"
                            value: "worker"
                ```
                """
            ),
            "DO": cleandoc(
                """
                Below is an example of how to set the `kube_context` field in the
                event that you need to specify the correct cluster, when deploying into
                an existing Digital Ocean infrastructure:
                ```yaml
                existing:
                    kube_context: <cluster_name>
                    node_selectors:
                        general:
                            key: "doks.digitalocean.com/node-pool"
                            value: "general"
                        user:
                            key: "doks.digitalocean.com/node-pool"
                            value: "user"
                        worker:
                            key: "doks.digitalocean.com/node-pool"
                            value: "worker"
                ```
                """
            ),
        },
        # group_by="provider",
    )
    google_cloud_platform: Optional[GoogleCloudPlatformProvider] = Field(
        default_factory=lambda: GoogleCloudPlatformProvider(),
        description=cleandoc(
            """
            The Google Cloud Platform provider is tailored for deploying Nebari on GCP's
            robust, secure, and scalable infrastructure. It enables seamless integration
            with GCP services like Google Kubernetes Engine (GKE), ensuring optimized
            performance and management for enterprise-grade applications.
            """
        ),
        depends_on={"provider": schema.ProviderEnum.gcp},
        examples=[
            cleandoc(
                """
                Below is a full example of how the defaults values are set for the
                Google Cloud Platform provider:
                ```yaml
                google_cloud_platform:
                    region: us-central1
                    project: my-project
                    kubernetes_version: 1.21.4-gke.2300
                    availability_zones:
                        - us-central1-a
                        - us-central1-b
                    node_groups:
                        general:
                            instance: n1-standard-4
                            min_nodes: 1
                            max_nodes: 1
                        user:
                            instance: n1-standard-4
                            min_nodes: 0
                            max_nodes: 5
                        worker:
                            instance: n1-standard-4
                            min_nodes: 0
                            max_nodes: 5
                ```
                """
            )
        ],
        # group_by="provider",
    )
    amazon_web_services: Optional[AmazonWebServicesProvider] = Field(
        default_factory=lambda: AmazonWebServicesProvider(),
        description=cleandoc(
            """
            This provider facilitates Nebari deployments on [Amazon Web Services (AWS)](https://aws.amazon.com/eks/), leveraging
            AWS's extensive cloud capabilities.
            """
        ),
        depends_on={"provider": schema.ProviderEnum.aws},
        examples=[
            cleandoc(
                """
                Below is a full example of how the defaults values are set for the
                AWS provider:
                ```yaml
                amazon_web_services:
                    region: us-west-2
                    kubernetes_version: 1.21
                    availability_zones:
                        - us-west-2a
                        - us-west-2b
                    node_groups:
                        general:
                            instance: m5.2xlarge
                            min_nodes: 1
                            max_nodes: 1
                        user:
                            instance: m5.xlarge
                            min_nodes: 0
                            max_nodes: 5
                        worker:
                            instance: m5.xlarge
                            min_nodes: 0
                            max_nodes: 5
                ```
                """
            )
        ],
        # group_by="provider",
    )
    azure: Optional[AzureProvider] = Field(
        default_factory=lambda: AzureProvider(),
        description=cleandoc(
            """
            Azure provider supports deploying Nebari on Microsoft Azure's cloud
            platform, using Azure Kubernetes Service (AKS). This provider is perfect for
            enterprises that require integration with Microsoft's cloud ecosystem and
            want to benefit from Azure's enterprise-focused services and security
            features.
            """
        ),
        depends_on={"provider": schema.ProviderEnum.azure},
        examples=[
            cleandoc(
                """
                Below is a full example of how the defaults values are set for the
                Azure provider:
                ```yaml
                azure:
                    region: eastus
                    kubernetes_version: 1.21.4
                    resource_group_name: my-resource-group
                    vnet_subnet_id: my-vnet-subnet-id
                    private_cluster_enabled: false
                    tags:
                        my-tag-key: my-tag-value
                    node_groups:
                        general:
                            instance: Standard_D4_v4
                            min_nodes: 1
                            max_nodes: 1
                        user:
                            instance: Standard_D4_v4
                            min_nodes: 0
                            max_nodes: 5
                        worker:
                            instance: Standard_D4_v4
                            min_nodes: 0
                            max_nodes: 5
                ```
                """
            )
        ],
        # group_by="provider",
    )
    digital_ocean: Optional[DigitalOceanProvider] = Field(
        default_factory=lambda: DigitalOceanProvider(),
        description=cleandoc(
            """
            Designed for Nebari deployments on Digital Ocean, this provider simplifies
            the process of managing Kubernetes clusters through Digital Ocean Kubernetes
            (DOKS) and their on demand machines, called Droplets.

            It's a great choice for users looking to deploy applications on a cloud
            platform that's easy to use, while offering a wide range of services and
            integrations.
            """
        ),
        note=cleandoc(
            """
            By default, Nebari will render and apply the default values during its first
            initialization and deployment. For extra details about how these values are
            assigned, please refer to the
            [initialize.py](https://github.com/nebari-dev/nebari/blob/develop/src/_nebari/initialize.py#L120-L133)
            file.
            """
        ),
        depends_on={"provider": schema.ProviderEnum.do},
        examples=[
            cleandoc(
                """
                Below is a full example of how the defaults values are set for the
                Digital Ocean provider:
                ```yaml
                digital_ocean:
                    region: nyc1
                    kubernetes_version: 1.21.4-do.0
                    node_groups:
                        general:
                            instance: s-4vcpu-8gb
                            min_nodes: 1
                            max_nodes: 1
                        user:
                            instance: s-4vcpu-8gb
                            min_nodes: 0
                            max_nodes: 5
                        worker:
                            instance: s-4vcpu-8gb
                            min_nodes: 0
                            max_nodes: 5
                ```
                """
            )
        ],
        # group_by="provider",
    )

    # NOTE: This will most probably be refactor as part of #2497
    @model_validator(mode="before")
    @classmethod
    def check_provider(cls, data: Any) -> Any:
        if "provider" in data:
            provider: str = data["provider"]
            if hasattr(schema.ProviderEnum, provider):
                # TODO: all cloud providers has required fields, but local and existing don't.
                #  And there is no way to initialize a model without user input here.
                #  We preserve the original behavior here, but we should find a better way to do this.
                if provider in ["local", "existing"] and provider not in data:
                    data[provider] = provider_enum_model_map[provider]()
            else:
                # if the provider field is invalid, it won't be set when this validator is called
                # so we need to check for it explicitly here, and set the `pre` to True
                # TODO: this is a workaround, check if there is a better way to do this in Pydantic v2
                raise ValueError(
                    f"'{provider}' is not a valid enumeration member; permitted: local, existing, do, aws, gcp, azure"
                )
        else:
            setted_providers = [
                provider
                for provider in provider_name_abbreviation_map.keys()
                if provider in data
            ]
            num_providers = len(setted_providers)
            if num_providers > 1:
                raise ValueError(f"Multiple providers set: {setted_providers}")
            elif num_providers == 1:
                data["provider"] = provider_name_abbreviation_map[setted_providers[0]]
            elif num_providers == 0:
                data["provider"] = schema.ProviderEnum.local.value
        return data


class NodeSelectorKeyValue(schema.Base):
    key: str
    value: str


class KubernetesCredentials(schema.Base):
    host: str
    cluster_ca_certifiate: str
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    client_certificate: Optional[str] = None
    client_key: Optional[str] = None
    config_path: Optional[str] = None
    config_context: Optional[str] = None


class OutputSchema(schema.Base):
    node_selectors: Dict[str, NodeSelectorKeyValue]
    kubernetes_credentials: KubernetesCredentials
    kubeconfig_filename: str
    nfs_endpoint: Optional[str] = None


class KubernetesInfrastructureStage(NebariTerraformStage):
    """Generalized method to provision infrastructure.

    After successful deployment the following properties are set on
    `stage_outputs[directory]`.
      - `kubernetes_credentials` which are sufficient credentials to
        connect with the kubernetes provider
      - `kubeconfig_filename` which is a path to a kubeconfig that can
        be used to connect to a kubernetes cluster
      - at least one node running such that resources in the
        node_group.general can be scheduled

    At a high level this stage is expected to provision a kubernetes
    cluster on a given provider.
    """

    name = "02-infrastructure"
    priority = 20

    input_schema = InputSchema
    output_schema = OutputSchema

    @property
    def template_directory(self):
        return (
            pathlib.Path(inspect.getfile(self.__class__)).parent
            / "template"
            / self.config.provider.value
        )

    @property
    def stage_prefix(self):
        return pathlib.Path("stages") / self.name / self.config.provider.value

    def state_imports(self) -> List[Tuple[str, str]]:
        if self.config.provider == schema.ProviderEnum.azure:
            if self.config.azure.resource_group_name is None:
                return []

            subscription_id = os.environ["ARM_SUBSCRIPTION_ID"]
            resource_group_name = construct_azure_resource_group_name(
                project_name=self.config.project_name,
                namespace=self.config.namespace,
                base_resource_group_name=self.config.azure.resource_group_name,
            )
            resource_url = (
                f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}"
            )
            return [
                (
                    "azurerm_resource_group.resource_group",
                    resource_url,
                )
            ]

    def tf_objects(self) -> List[Dict]:
        if self.config.provider == schema.ProviderEnum.gcp:
            return [
                terraform.Provider(
                    "google",
                    project=self.config.google_cloud_platform.project,
                    region=self.config.google_cloud_platform.region,
                ),
                NebariTerraformState(self.name, self.config),
            ]
        elif self.config.provider == schema.ProviderEnum.do:
            return [
                NebariTerraformState(self.name, self.config),
            ]
        elif self.config.provider == schema.ProviderEnum.azure:
            return [
                NebariTerraformState(self.name, self.config),
            ]
        elif self.config.provider == schema.ProviderEnum.aws:
            return [
                terraform.Provider(
                    "aws", region=self.config.amazon_web_services.region
                ),
                NebariTerraformState(self.name, self.config),
            ]
        else:
            return []

    def input_vars(self, stage_outputs: Dict[str, Dict[str, Any]]):
        if self.config.provider == schema.ProviderEnum.local:
            return LocalInputVars(
                kube_context=self.config.local.kube_context
            ).model_dump()
        elif self.config.provider == schema.ProviderEnum.existing:
            return ExistingInputVars(
                kube_context=self.config.existing.kube_context
            ).model_dump()
        elif self.config.provider == schema.ProviderEnum.do:
            return DigitalOceanInputVars(
                name=self.config.escaped_project_name,
                environment=self.config.namespace,
                region=self.config.digital_ocean.region,
                tags=self.config.digital_ocean.tags,
                kubernetes_version=self.config.digital_ocean.kubernetes_version,
                node_groups=self.config.digital_ocean.node_groups,
            ).model_dump()
        elif self.config.provider == schema.ProviderEnum.gcp:
            return GCPInputVars(
                name=self.config.escaped_project_name,
                environment=self.config.namespace,
                region=self.config.google_cloud_platform.region,
                project_id=self.config.google_cloud_platform.project,
                availability_zones=self.config.google_cloud_platform.availability_zones,
                node_groups=[
                    GCPNodeGroupInputVars(
                        name=name,
                        labels=node_group.labels,
                        instance_type=node_group.instance,
                        min_size=node_group.min_nodes,
                        max_size=node_group.max_nodes,
                        preemptible=node_group.preemptible,
                        guest_accelerators=node_group.guest_accelerators,
                    )
                    for name, node_group in self.config.google_cloud_platform.node_groups.items()
                ],
                tags=self.config.google_cloud_platform.tags,
                kubernetes_version=self.config.google_cloud_platform.kubernetes_version,
                release_channel=self.config.google_cloud_platform.release_channel,
                networking_mode=self.config.google_cloud_platform.networking_mode,
                network=self.config.google_cloud_platform.network,
                subnetwork=self.config.google_cloud_platform.subnetwork,
                ip_allocation_policy=self.config.google_cloud_platform.ip_allocation_policy,
                master_authorized_networks_config=self.config.google_cloud_platform.master_authorized_networks_config,
                private_cluster_config=self.config.google_cloud_platform.private_cluster_config,
            ).model_dump()
        elif self.config.provider == schema.ProviderEnum.azure:
            return AzureInputVars(
                name=self.config.escaped_project_name,
                environment=self.config.namespace,
                region=self.config.azure.region,
                kubernetes_version=self.config.azure.kubernetes_version,
                node_groups={
                    name: AzureNodeGroupInputVars(
                        instance=node_group.instance,
                        min_nodes=node_group.min_nodes,
                        max_nodes=node_group.max_nodes,
                    )
                    for name, node_group in self.config.azure.node_groups.items()
                },
                resource_group_name=construct_azure_resource_group_name(
                    project_name=self.config.project_name,
                    namespace=self.config.namespace,
                    base_resource_group_name=self.config.azure.resource_group_name,
                ),
                node_resource_group_name=construct_azure_resource_group_name(
                    project_name=self.config.project_name,
                    namespace=self.config.namespace,
                    base_resource_group_name=self.config.azure.resource_group_name,
                    suffix=AZURE_NODE_RESOURCE_GROUP_SUFFIX,
                ),
                vnet_subnet_id=self.config.azure.vnet_subnet_id,
                private_cluster_enabled=self.config.azure.private_cluster_enabled,
                tags=self.config.azure.tags,
                network_profile=self.config.azure.network_profile,
                max_pods=self.config.azure.max_pods,
            ).model_dump()
        elif self.config.provider == schema.ProviderEnum.aws:
            return AWSInputVars(
                name=self.config.escaped_project_name,
                environment=self.config.namespace,
                existing_subnet_ids=self.config.amazon_web_services.existing_subnet_ids,
                existing_security_group_id=self.config.amazon_web_services.existing_security_group_id,
                region=self.config.amazon_web_services.region,
                kubernetes_version=self.config.amazon_web_services.kubernetes_version,
                node_groups=[
                    AWSNodeGroupInputVars(
                        name=name,
                        instance_type=node_group.instance,
                        gpu=node_group.gpu,
                        min_size=node_group.min_nodes,
                        desired_size=node_group.min_nodes,
                        max_size=node_group.max_nodes,
                        single_subnet=node_group.single_subnet,
                        permissions_boundary=node_group.permissions_boundary,
                    )
                    for name, node_group in self.config.amazon_web_services.node_groups.items()
                ],
                availability_zones=self.config.amazon_web_services.availability_zones,
                vpc_cidr_block=self.config.amazon_web_services.vpc_cidr_block,
                permissions_boundary=self.config.amazon_web_services.permissions_boundary,
                tags=self.config.amazon_web_services.tags,
            ).model_dump()
        else:
            raise ValueError(f"Unknown provider: {self.config.provider}")

    def check(
        self, stage_outputs: Dict[str, Dict[str, Any]], disable_prompt: bool = False
    ):
        from kubernetes import client, config
        from kubernetes.client.rest import ApiException

        config.load_kube_config(
            config_file=stage_outputs["stages/02-infrastructure"][
                "kubeconfig_filename"
            ]["value"]
        )

        try:
            api_instance = client.CoreV1Api()
            result = api_instance.list_namespace()
        except ApiException:
            print(
                f"ERROR: After stage={self.name} unable to connect to kubernetes cluster"
            )
            sys.exit(1)

        if len(result.items) < 1:
            print(
                f"ERROR: After stage={self.name} no nodes provisioned within kubernetes cluster"
            )
            sys.exit(1)

        print(f"After stage={self.name} kubernetes cluster successfully provisioned")

    def set_outputs(
        self, stage_outputs: Dict[str, Dict[str, Any]], outputs: Dict[str, Any]
    ):
        outputs["node_selectors"] = _calculate_node_groups(self.config)
        super().set_outputs(stage_outputs, outputs)

    @contextlib.contextmanager
    def post_deploy(
        self, stage_outputs: Dict[str, Dict[str, Any]], disable_prompt: bool = False
    ):
        asg_node_group_map = _calculate_asg_node_group_map(self.config)
        if asg_node_group_map:
            amazon_web_services.set_asg_tags(
                asg_node_group_map, self.config.amazon_web_services.region
            )

    @contextlib.contextmanager
    def deploy(
        self, stage_outputs: Dict[str, Dict[str, Any]], disable_prompt: bool = False
    ):
        with super().deploy(stage_outputs, disable_prompt):
            with kubernetes_provider_context(
                stage_outputs["stages/" + self.name]["kubernetes_credentials"]["value"]
            ):
                yield

    @contextlib.contextmanager
    def destroy(
        self, stage_outputs: Dict[str, Dict[str, Any]], status: Dict[str, bool]
    ):
        with super().destroy(stage_outputs, status):
            with kubernetes_provider_context(
                stage_outputs["stages/" + self.name]["kubernetes_credentials"]["value"]
            ):
                yield


@hookimpl
def nebari_stage() -> List[Type[NebariStage]]:
    return [KubernetesInfrastructureStage]
