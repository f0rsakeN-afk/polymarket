from uuid import UUID
from pydantic import BaseModel, field_validator


class BaseSchema(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def convert_uuid(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v
