from typing import Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, RootModel

GLCI_extras = RootModel[Union[str, float, int]]


class GLCI_image(BaseModel):
    name: str
    entrypoint: Optional[str] = None


class GLCI_rules(BaseModel):
    if_: Optional[str] = Field(alias="if")
    changes: Optional[List[str]] = None
    model_config = ConfigDict(populate_by_name=True)


class GLCI_job(BaseModel):
    image: Optional[Union[str, GLCI_image]] = None
    variables: Optional[Dict[str, str]] = None
    before_script: Optional[List[str]] = None
    after_script: Optional[List[str]] = None
    script: List[str]
    rules: Optional[List[GLCI_rules]] = None


GLCI = RootModel[Dict[str, GLCI_job]]
