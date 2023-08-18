import os


def pip_install_nebari(nebari_version: str) -> str:
    nebari_gh_branch = os.environ.get("NEBARI_GH_BRANCH", None)
    nebari_source_repo = os.environ.get(
        "NEBARI_SOURCE_REPO", "https://github.com/nebari-dev/nebari.git"
    )
    pip_install = f"pip install nebari=={nebari_version}"
    # dev branches
    if nebari_gh_branch:
        pip_install = f"pip install git+{nebari_source_repo}@{nebari_gh_branch}"

    return pip_install
