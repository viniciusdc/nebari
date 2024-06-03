import contextlib
import enum
import inspect
import os
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple, Type
from inspect import cleandoc

from pydantic import field_validator, Field, model_validator

from _nebari.provider import terraform
from _nebari.provider.cloud import azure_cloud
from _nebari.stages.base import NebariTerraformStage
from _nebari.utils import (
    AZURE_TF_STATE_RESOURCE_GROUP_SUFFIX,
    construct_azure_resource_group_name,
    modified_environ,
)
from nebari import schema
from nebari.hookspecs import NebariStage, hookimpl


class DigitalOceanInputVars(schema.Base):
    name: str
    namespace: str
    region: str


class GCPInputVars(schema.Base):
    name: str
    namespace: str
    region: str


class AzureInputVars(schema.Base):
    name: str
    namespace: str
    region: str
    storage_account_postfix: str
    state_resource_group_name: str
    tags: Dict[str, str]

    @field_validator("state_resource_group_name")
    @classmethod
    def _validate_resource_group_name(cls, value: str) -> str:
        if value is None:
            return value
        length = len(value) + len(AZURE_TF_STATE_RESOURCE_GROUP_SUFFIX)
        if length < 1 or length > 90:
            raise ValueError(
                f"Azure Resource Group name must be between 1 and 90 characters long, when combined with the suffix `{AZURE_TF_STATE_RESOURCE_GROUP_SUFFIX}`."
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
    def _validate_tags(cls, value: Dict[str, str]) -> Dict[str, str]:
        return azure_cloud.validate_tags(value)


class AWSInputVars(schema.Base):
    name: str
    namespace: str


@schema.yaml_object(schema.yaml)
class TerraformStateEnum(str, enum.Enum):
    remote = "remote"
    local = "local"
    existing = "existing"

    @classmethod
    def to_yaml(cls, representer, node):
        return representer.represent_str(node.value)


class TerraformState(schema.Base):
    type: TerraformStateEnum = Field(
        default=TerraformStateEnum.remote,
        description=cleandoc(
            """
            Selects the Terraform state management type:

            - `remote`: Sets up a remote state backend using pre-configured settings
              appropriate for the chosen cloud provider. Compatible with all
              S3-compatible storage options available through Nebari's supported
              providers.
            - `local`: Stores the state data locally within the `state` directory at the
              project's root.
            - `existing`: Enable further options to non-standard Nebari state backends,
              such as `consul` or `kubernetes`.

            Nebari supports these options to cater to various development needs and
            preferences. It is important to choose carefully as these options are
            mutually exclusive. Switching state types after project initialization is
            discouraged due to the risk of state corruption.
            """
        ),
        optionsAre=[state.value for state in TerraformStateEnum],
        note=cleandoc(
            """
            If you opt for the `local` state type, it's crucial to keep the `state`
            files intact and unaltered to avoid inconsistencies during deployment.
            Its recommended to use the `remote` state type for production deployments as
            it grants safe-guards like state locking to prevent conflicts during
            concurrent operations.
            """
        ),
    )
    backend: Optional[str] = Field(
        default=None,
        description=cleandoc(
            """
            Specifies the Terraform backend to manage state data, applicable **only**
            when using the `existing` state type.

            A backend determines the storage location for Terraform's state files, which
            track managed resources. Nebari handles this automatically for the `remote`
            state type, but for `existing` state types, you must provide the backend
            configuration manually.
            """
        ),
        note=cleandoc(
            """
            For a full overview of Terraform's supported backends and their
            configuration, visit the [Terraform Backends documentation](https://developer.hashicorp.com/terraform/language/settings/backends/configuration).
            """
        ),
        depends_ond={"type": TerraformStateEnum.existing},
    )
    config: Dict[str, str] = Field(
        default_factory=dict,
        description=cleandoc(
            """
            Configuration for the Terraform backend, only supported if using
            with the existing terraform state type. For a complete list of
            supported backends and their configuration options, see the [Terraform
            Backednds](https://developer.hashicorp.com/terraform/language/settings/backends/configuration#available-backends)
            documentation.
            ```
            """
        ),
        examples=[
            cleandoc(
                """
                Bellow is an example of the configuration for the Terraform backend
                when using an existing state backend from a supported provider. In this
                example, we've configured the backend to use the [Kubernetes secret
                backend](https://developer.hashicorp.com/terraform/language/settings/backends/kubernetes)
                with the following configuration options:

                ```yaml
                backend: kubernetes
                config:
                    secret_suffix: my-secret-suffix
                    labels:
                        my-label: my-value
                    namespace: my-namespace
                    in_cluster_config: true
                ```
                """
            ),
        ],
        depends_on={"type": TerraformStateEnum.existing},
    )

    @model_validator(mode="after")
    def validate_fields(self) -> "TerraformState":
        # 'remote' and 'local' types should not have backend or config fields
        if self.type in [TerraformStateEnum.remote, TerraformStateEnum.local]:
            if any([self.backend is not None, self.config]):
                field = "backend" if self.backend is not None else "config"
                raise ValueError(
                    f"The `{field}` field is not supported for the `{self.type.name}` state type."
                )

        elif self.type == TerraformStateEnum.existing:
            if any([self.backend is None, not self.config]):
                field = "backend" if self.backend is None else "config"
                raise ValueError(
                    f"The `{field}` field is required for the `existing` state type."
                )

        return self


class InputSchema(schema.Base):
    terraform_state: TerraformState = Field(
        default_factory=lambda: TerraformState(),
        description=cleandoc(
            """
            [Terraform state](https://developer.hashicorp.com/terraform/language/state)
            configuration, required by terraform to securely store the state of the
            terraform deployment, to be provisioned and stored remotely, locally on the
            filesystem, or using existing terraform state backend.

            Which ranges from using:
            - `GCS` for Google Cloud Platform
            - `S3` for Amazon Web Services
            - `Spaces` (S3 compatible) for DigitalOcean
            - `azurerm` for Microsoft Azure
            """
        ),
        examples=[
            cleandoc(
                """
                Bellow we provide a basic example of the Terraform state configuration
                for a default deployment. When opting by remote, `nebari` will
                automatically provision a remote state backend using the pre-build
                settings for the selected cloud provider.

                ```yaml
                terraform_state:
                  type: remote
                ```
                """
            )
        ],
    )


class OutputSchema(schema.Base):
    pass


class TerraformStateStage(NebariTerraformStage):
    name = "01-terraform-state"
    priority = 10

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
        if self.config.provider == schema.ProviderEnum.do:
            return [
                (
                    "module.terraform-state.module.spaces.digitalocean_spaces_bucket.main",
                    f"{self.config.digital_ocean.region},{self.config.project_name}-{self.config.namespace}-terraform-state",
                )
            ]
        elif self.config.provider == schema.ProviderEnum.gcp:
            return [
                (
                    "module.terraform-state.module.gcs.google_storage_bucket.static-site",
                    f"{self.config.project_name}-{self.config.namespace}-terraform-state",
                )
            ]
        elif self.config.provider == schema.ProviderEnum.azure:
            subscription_id = os.environ["ARM_SUBSCRIPTION_ID"]
            resource_name_prefix = f"{self.config.project_name}-{self.config.namespace}"
            state_resource_group_name = construct_azure_resource_group_name(
                project_name=self.config.project_name,
                namespace=self.config.namespace,
                base_resource_group_name=self.config.azure.resource_group_name,
                suffix=AZURE_TF_STATE_RESOURCE_GROUP_SUFFIX,
            )
            state_resource_name_prefix_safe = resource_name_prefix.replace("-", "")
            resource_group_url = f"/subscriptions/{subscription_id}/resourceGroups/{state_resource_group_name}"

            return [
                (
                    "module.terraform-state.azurerm_resource_group.terraform-state-resource-group",
                    resource_group_url,
                ),
                (
                    "module.terraform-state.azurerm_storage_account.terraform-state-storage-account",
                    f"{resource_group_url}/providers/Microsoft.Storage/storageAccounts/{state_resource_name_prefix_safe}{self.config.azure.storage_account_postfix}",
                ),
                (
                    "module.terraform-state.azurerm_storage_container.storage_container",
                    f"https://{state_resource_name_prefix_safe}{self.config.azure.storage_account_postfix}.blob.core.windows.net/{resource_name_prefix}-state",
                ),
            ]
        elif self.config.provider == schema.ProviderEnum.aws:
            return [
                (
                    "module.terraform-state.aws_s3_bucket.terraform-state",
                    f"{self.config.project_name}-{self.config.namespace}-terraform-state",
                ),
                (
                    "module.terraform-state.aws_dynamodb_table.terraform-state-lock",
                    f"{self.config.project_name}-{self.config.namespace}-terraform-state-lock",
                ),
            ]
        else:
            return []

    def tf_objects(self) -> List[Dict]:
        if self.config.provider == schema.ProviderEnum.gcp:
            return [
                terraform.Provider(
                    "google",
                    project=self.config.google_cloud_platform.project,
                    region=self.config.google_cloud_platform.region,
                ),
            ]
        elif self.config.provider == schema.ProviderEnum.aws:
            return [
                terraform.Provider(
                    "aws", region=self.config.amazon_web_services.region
                ),
            ]
        else:
            return []

    def input_vars(self, stage_outputs: Dict[str, Dict[str, Any]]):
        if self.config.provider == schema.ProviderEnum.do:
            return DigitalOceanInputVars(
                name=self.config.project_name,
                namespace=self.config.namespace,
                region=self.config.digital_ocean.region,
            ).model_dump()
        elif self.config.provider == schema.ProviderEnum.gcp:
            return GCPInputVars(
                name=self.config.project_name,
                namespace=self.config.namespace,
                region=self.config.google_cloud_platform.region,
            ).model_dump()
        elif self.config.provider == schema.ProviderEnum.aws:
            return AWSInputVars(
                name=self.config.project_name,
                namespace=self.config.namespace,
            ).model_dump()
        elif self.config.provider == schema.ProviderEnum.azure:
            return AzureInputVars(
                name=self.config.project_name,
                namespace=self.config.namespace,
                region=self.config.azure.region,
                storage_account_postfix=self.config.azure.storage_account_postfix,
                state_resource_group_name=construct_azure_resource_group_name(
                    project_name=self.config.project_name,
                    namespace=self.config.namespace,
                    base_resource_group_name=self.config.azure.resource_group_name,
                    suffix=AZURE_TF_STATE_RESOURCE_GROUP_SUFFIX,
                ),
                tags=self.config.azure.tags,
            ).model_dump()
        elif (
            self.config.provider == schema.ProviderEnum.local
            or self.config.provider == schema.ProviderEnum.existing
        ):
            return {}
        else:
            ValueError(f"Unknown provider: {self.config.provider}")

    @contextlib.contextmanager
    def deploy(
        self, stage_outputs: Dict[str, Dict[str, Any]], disable_prompt: bool = False
    ):
        with super().deploy(stage_outputs, disable_prompt):
            env_mapping = {}
            # DigitalOcean terraform remote state using Spaces Bucket
            # assumes aws credentials thus we set them to match spaces credentials
            if self.config.provider == schema.ProviderEnum.do:
                env_mapping.update(
                    {
                        "AWS_ACCESS_KEY_ID": os.environ["SPACES_ACCESS_KEY_ID"],
                        "AWS_SECRET_ACCESS_KEY": os.environ["SPACES_SECRET_ACCESS_KEY"],
                    }
                )

            with modified_environ(**env_mapping):
                yield

    @contextlib.contextmanager
    def destroy(
        self, stage_outputs: Dict[str, Dict[str, Any]], status: Dict[str, bool]
    ):
        with super().destroy(stage_outputs, status):
            env_mapping = {}
            # DigitalOcean terraform remote state using Spaces Bucket
            # assumes aws credentials thus we set them to match spaces credentials
            if self.config.provider == schema.ProviderEnum.do:
                env_mapping.update(
                    {
                        "AWS_ACCESS_KEY_ID": os.environ["SPACES_ACCESS_KEY_ID"],
                        "AWS_SECRET_ACCESS_KEY": os.environ["SPACES_SECRET_ACCESS_KEY"],
                    }
                )

            with modified_environ(**env_mapping):
                yield


@hookimpl
def nebari_stage() -> List[Type[NebariStage]]:
    return [TerraformStateStage]
