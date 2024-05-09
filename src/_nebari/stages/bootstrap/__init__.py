import enum
import io
import json
import pathlib
import typing
from inspect import cleandoc
from typing import Dict, List, Type
from pydantic import Field

from _nebari.provider.cicd.github import gen_nebari_linter, gen_nebari_ops
from _nebari.provider.cicd.gitlab import gen_gitlab_ci
from nebari import schema
from nebari.hookspecs import NebariStage, hookimpl
import yaml


def gen_gitignore():
    """
    Generate `.gitignore` file.
    Add files as needed.
    """
    filestoignore = """
        # ignore terraform state
        .terraform
        terraform.tfstate
        terraform.tfstate.backup
        .terraform.tfstate.lock.info

        # python
        __pycache__
    """
    return {pathlib.Path(".gitignore"): cleandoc(filestoignore)}


def gen_cicd(config: schema.Main):
    """
    Use cicd schema to generate workflow files based on the
    `ci_cd` key in the `config`.

    For more detail on schema:
    GiHub-Actions - nebari/providers/cicd/github.py
    GitLab-CI - nebari/providers/cicd/gitlab.py
    """
    cicd_files = {}

    if config.ci_cd.type == CiEnum.github_actions:
        gha_dir = pathlib.Path(".github/workflows/")
        cicd_files[gha_dir / "nebari-ops.yaml"] = gen_nebari_ops(config)
        cicd_files[gha_dir / "nebari-linter.yaml"] = gen_nebari_linter(config)

    elif config.ci_cd.type == CiEnum.gitlab_ci:
        cicd_files[pathlib.Path(".gitlab-ci.yml")] = gen_gitlab_ci(config)

    else:
        raise ValueError(
            f"The ci_cd provider, {config.ci_cd.type.value}, is not supported. Supported providers include: `github-actions`, `gitlab-ci`."
        )

    return cicd_files


@schema.yaml_object(schema.yaml)
class CiEnum(str, enum.Enum):
    github_actions = "github-actions"
    gitlab_ci = "gitlab-ci"
    none = "none"

    @classmethod
    def to_yaml(cls, representer, node):
        return representer.represent_str(node.value)


class CICD(schema.Base):
    type: CiEnum = Field(
        default=CiEnum.none,
        description=cleandoc(
            f"""
            Specifies the CI/CD provider that is used to automate the deployment of your
            infrastructure.
            """
        ),
        optionsAre=[provider.value for provider in CiEnum],
        note=cleandoc(
            """
            If opted for `None`, no CI/CD configuration will be generated.
            """
        ),
    )
    branch: str = Field(
        default="main",
        description=cleandoc(
            """
            Defines the version control branch that CI/CD operations should track and
            use for deployments. This can be changed to any valid branch name.
            """
        ),
    )
    commit_render: bool = Field(
        default=True,
        description=cleandoc(
            """
            Determines whether the CI/CD process should automatically commit rendered
            configuration files or outputs back into the repository. This can be useful
            for tracking changes and ensuring that the latest configuration is always
            available in the repository.
            """
        ),
    )
    before_script: typing.List[typing.Union[str, typing.Dict]] = Field(
        default=[],
        depends_on={"type": CiEnum.gitlab_ci},
        description=cleandoc(
            """
            A list of scripts or commands that are executed prior to the main CI/CD
            pipeline actions.

            This can include setup scripts, pre-deployment checks, or any preparatory
            tasks that need to be completed before the main deployment process begins.

            It expects a list of tasks to be rendered in the same syntax as a the
            available CI/CD provider. Currently **only** supported on `gitlab-ci`.
            """
        ),
        examples=[
            cleandoc(
                """
                This might include installing dependencies, setting up
                environment variables, or running tests.

                ```yaml
                before_script:
                    - name: Export Environment Variables
                      run: "echo 'CREDENTIALS=${APPLICATION_CREDENTIALS}' >> $GITHUB_ENV"
                ```
                """
            )
        ],
    )
    after_script: typing.List[typing.Union[str, typing.Dict]] = Field(
        default=[],
        depends_on={"type": CiEnum.gitlab_ci},
        description=cleandoc(
            """
            A list of scripts or commands that are run after the main CI/CD pipeline
            actions have completed. This might include cleanup operations, notification
            sending, or other follow-up actions necessary to finalize the deployment
            process.

            It expects a list of tasks to be rendered in the same syntax as a the
            available CI/CD provider. Currently **only** supported on `gitlab-ci`.
            """
        ),
        examples=[
            cleandoc(
                """
                This might include sending notifications, cleaning up temporary
                files, or running post-deployment tests.

                ```yaml
                after_script:
                    - name: Send Notification
                      run: "echo 'Deployment Complete!'"
                ```
                """
            )
        ],
    )


class InputSchema(schema.Base):
    ci_cd: CICD = Field(
        default_factory=lambda: CICD(),
        description=cleandoc(
            """
            Nebari uses
            [infrastructure-as-code](https://en.wikipedia.org/wiki/Infrastructure_as_code)
            to allow developers and users to request changes to the environment via pull
            requests (PRs) which then get approved by administrators.

            You may configure a CI/CD process to watch for pull-requests or commits on
            specific branches. Currently, CI/CD can be setup for either [GitHub
            Actions](https://docs.github.com/en/actions) or [GitLab
            CI](https://docs.gitlab.com/ee/ci/).
            """
        ),
        examples=[
            cleandoc(
                f"""
                Below is an example of a CI/CD configuration that uses GitHub Actions as
                the provider. The configuration specifies that the CI/CD process should
                track the `main` branch, automatically commit rendered configuration
                files, and run before and after scripts.

                ```yaml
                ci_cd:
                    type: github-actions
                    branch: main
                    commit_render: true
                ```
                """
            )
        ],
        note=cleandoc(
            """
            If `ci_cd` is not supplied, no CI/CD will be auto-generated, however, we
            advise employing an infrastructure-as-code approach. This allows teams to
            more quickly modify their deployment, empowering developers and data
            scientists to request the changes and have them approved by an
            administrator.
            """
        ),
    )


class OutputSchema(schema.Base):
    pass


class BootstrapStage(NebariStage):
    name = "bootstrap"
    priority = 0

    input_schema = InputSchema
    output_schema = OutputSchema

    def render(self) -> Dict[str, str]:
        contents = {}
        if self.config.ci_cd.type != CiEnum.none:
            for fn, workflow in gen_cicd(self.config).items():
                stream = io.StringIO()
                schema.yaml.dump(
                    workflow.model_dump(
                        by_alias=True, exclude_unset=True, exclude_defaults=True
                    ),
                    stream,
                )
                contents.update({fn: stream.getvalue()})

        contents.update(gen_gitignore())
        return contents


@hookimpl
def nebari_stage() -> List[Type[NebariStage]]:
    return [BootstrapStage]
