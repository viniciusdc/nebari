from typing import Dict, List, Optional, Union

from nacl import encoding, public
from pydantic import BaseModel, ConfigDict, Field, RootModel


class GHA_on_extras(BaseModel):
    branches: List[str]
    paths: List[str]


GHA_on = RootModel[Dict[str, GHA_on_extras]]
GHA_job_steps_extras = RootModel[Union[str, float, int]]


class GHA_job_step(BaseModel):
    name: str
    uses: Optional[str] = None
    with_: Optional[Dict[str, GHA_job_steps_extras]] = Field(alias="with", default=None)
    run: Optional[str] = None
    env: Optional[Dict[str, GHA_job_steps_extras]] = None
    model_config = ConfigDict(populate_by_name=True)


class GHA_job_id(BaseModel):
    name: str
    runs_on_: str = Field(alias="runs-on")
    permissions: Optional[Dict[str, str]] = None
    steps: List[GHA_job_step]
    model_config = ConfigDict(populate_by_name=True)


GHA_jobs = RootModel[Dict[str, GHA_job_id]]


class GHA(BaseModel):
    name: str
    on: GHA_on
    env: Optional[Dict[str, str]] = None
    jobs: GHA_jobs


class NebariOps(GHA):
    pass


class NebariLinter(GHA):
    pass
