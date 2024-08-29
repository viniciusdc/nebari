import argparse
import contextlib
import json
import logging
import pathlib

from _nebari.config import read_configuration
from _nebari.utils import timer
from nebari import hookspecs
from nebari.plugins import nebari_plugin_manager

CONFIG_FILENAME = "nebari-config.yaml"
REL_PREFIX = ""


def main(tmp_dir: str):
    # Set up directories
    output_directory = pathlib.Path.cwd()
    print(f"Running on {output_directory}")

    # Configure logging
    logger = logging.getLogger(__name__)

    # Retrieve plugin stages and config schema
    stages = nebari_plugin_manager.ordered_stages
    config_schema = nebari_plugin_manager.config_schema

    # Read configuration
    config = read_configuration(
        output_directory / REL_PREFIX / CONFIG_FILENAME, config_schema=config_schema
    )

    # Deploy Nebari
    with timer(logger, "deploying Nebari"):
        stage_outputs = {}
        with contextlib.ExitStack() as stack:
            for stage in stages:
                s: hookspecs.NebariStage = stage(
                    output_directory=output_directory / REL_PREFIX, config=config
                )
                stack.enter_context(s.plan(stage_outputs, tmp_dir))

                (output_directory / REL_PREFIX / "outputs").mkdir(
                    parents=True, exist_ok=True
                )

                with open(
                    output_directory / REL_PREFIX / "outputs" / stage.name, "w"
                ) as f:
                    f.write(json.dumps(stage_outputs))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check Nebari deployment integrity")
    parser.add_argument(
        "--tmp-dir", required=True, help="Temporary directory for artifacts"
    )
    # parser.add_argument(
    #     "--workspace-dir",
    #     required=True,
    #     help="Directory to check for Nebari deployment",
    # )

    args = parser.parse_args()

    main(args.tmp_dir)
