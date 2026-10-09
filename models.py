from typing import Literal
from pydantic import BaseModel,ConfigDict,Field

class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["approve","reject"]
    expected_version: int = Field(ge=1,strict=True)
    idempotency_key: str = Field(min_length=8,max_length=128)
    correlation_id: str = Field(min_length=8,max_length=128)

class WidgetDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1,max_length=64)
    expected_version: int = Field(ge=1,strict=True)
    idempotency_key: str = Field(min_length=8,max_length=128)
    correlation_id: str = Field(min_length=8,max_length=128)

class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3,max_length=64)
    password: str = Field(min_length=1,max_length=256)
