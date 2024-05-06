import enum
from typing import Annotated

import pydantic
from pydantic import ConfigDict, Field, StringConstraints, field_validator
from ruamel.yaml import yaml_object

from _nebari.utils import escape_string, yaml
from _nebari.version import __version__, rounded_ver_parse

# cleandoc is a function from the textwrap module
from inspect import cleandoc

# Regex for suitable project names
project_name_regex = r"^[A-Za-z][A-Za-z0-9\-_]{1,14}[A-Za-z0-9]$"
project_name_pydantic = Annotated[str, StringConstraints(pattern=project_name_regex)]

# Regex for suitable namespaces
namespace_regex = r"^[A-Za-z][A-Za-z\-_]*[A-Za-z]$"
namespace_pydantic = Annotated[str, StringConstraints(pattern=namespace_regex)]

email_regex = "^[^ @]+@[^ @]+\\.[^ @]+$"
email_pydantic = Annotated[str, StringConstraints(pattern=email_regex)]

github_url_regex = "^(https://)?github.com/([^/]+)/([^/]+)/?$"
github_url_pydantic = Annotated[str, StringConstraints(pattern=github_url_regex)]


class Base(pydantic.BaseModel):
    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, populate_by_name=True
    )


@yaml_object(yaml)
class ProviderEnum(str, enum.Enum):
    local = "local"
    existing = "existing"
    do = "do"
    aws = "aws"
    gcp = "gcp"
    azure = "azure"

    @classmethod
    def to_yaml(cls, representer, node):
        return representer.represent_str(node.value)


class Main(Base):
    project_name: str = Field(
        ...,
        pattern=project_name_regex,
        description=cleandoc(
            """
            Determines the base name for all major infrastructure related resources on
            Nebari. Should be compatible with the Cloud provider's naming conventions.
            See [Project Naming
            Conventions](/docs/explanations/config-best-practices#naming-conventions)
            for more details.
        """
        ),
    )
    namespace: str = Field(
        default="dev",
        pattern=namespace_regex,
        description=cleandoc(
            """
            Used in combination with `project_name` to label infrastructure related
            resources on Nebari and also determines the target
            [namespace](https://kubernetes.io/docs/concepts/overview/working-with-objects/namespaces/)
            used when deploying kubernetes resources. Defaults to `dev`.
        """
        ),
    )
    provider: ProviderEnum = Field(
        default=ProviderEnum.local,
        description=cleandoc(
            """
            Determines the cloud provider used to deploy infrastructure related
            resources on Nebari.

            Options include:
            - `local`,
            - `existing`,
            - `do`,
            - `aws`,
            - `gcp`,
            - `azure`

            For more information on the different providers, see [Nebari Deployment
            Platforms](/docs/get-started/deploy). Defaults to `local`.
        """
        ),
    )
    nebari_version: str = Field(
        default=__version__,
        description=cleandoc(
            """
            The current installed version of Nebari. This is used to determine if the
            schema's version, the user must run `nebari upgrade` to ensure
            compatibility.
        """
        ),
    )
    prevent_deploy: bool = Field(
        default=False,
        description=cleandoc(
            """
            Controls whether deployment is blocked post-upgrade. Setting this field to
            'True' helps ensure that users do not inadvertently redeploy without being
            aware of necessary configurations and updates, thus safeguarding the
            stability and integrity of the deployment. Defaults to 'False'.
        """
        ),
    )

    # If the nebari_version in the schema is old
    # we must tell the user to first run nebari upgrade
    @field_validator("nebari_version")
    @classmethod
    def check_default(cls, value):
        assert cls.is_version_accepted(
            value
        ), f"nebari_version={value} is not an accepted version, it must be equivalent to {__version__}.\nInstall a different version of nebari or run nebari upgrade to ensure your config file is compatible."
        return value

    @classmethod
    def is_version_accepted(cls, v):
        return v != "" and rounded_ver_parse(v) == rounded_ver_parse(__version__)

    @property
    def escaped_project_name(self):
        """Escaped project-name know to be compatible with all clouds"""
        project_name = self.project_name

        if self.provider == ProviderEnum.azure and "-" in project_name:
            project_name = escape_string(project_name, escape_char="a")

        if self.provider == ProviderEnum.aws and project_name.startswith("aws"):
            project_name = "a" + project_name

        return project_name


def is_version_accepted(v):
    """
    Given a version string, return boolean indicating whether
    nebari_version in the nebari-config.yaml would be acceptable
    for deployment with the current Nebari package.
    """
    return Main.is_version_accepted(v)
