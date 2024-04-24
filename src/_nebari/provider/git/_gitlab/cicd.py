from _nebari.constants import LATEST_SUPPORTED_PYTHON_VERSION
from _nebari.provider.cicd.common import pip_install_nebari

from .schema import *


def gen_gitlab_ci(config):
    render_vars = {
        "COMMIT_MSG": "nebari-config.yaml automated commit: {{ '$CI_COMMIT_SHA' }}",
    }

    script = [
        f"git checkout {config.ci_cd.branch}",
        pip_install_nebari(config.nebari_version),
        "nebari deploy --config nebari-config.yaml --disable-prompt --skip-remote-state-provision",
    ]

    commit_render_script = [
        "git config user.email 'nebari@quansight.com'",
        "git config user.name 'gitlab ci'",
        "git add .",
        "git diff --quiet && git diff --staged --quiet || (git commit -m '${COMMIT_MSG}'",
        f"git push origin {config.ci_cd.branch})",
    ]

    if config.ci_cd.commit_render:
        script += commit_render_script

    rules = [
        GLCI_rules(
            if_=f"$CI_COMMIT_BRANCH == '{config.ci_cd.branch}'",
            changes=["nebari-config.yaml"],
        )
    ]

    render_nebari = GLCI_job(
        image=f"python:{LATEST_SUPPORTED_PYTHON_VERSION}",
        variables=render_vars,
        before_script=config.ci_cd.before_script,
        after_script=config.ci_cd.after_script,
        script=script,
        rules=rules,
    )

    return GLCI(
        {
            "render-nebari": render_nebari,
        }
    )
