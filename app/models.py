from pydantic import BaseModel, Field
from typing import Optional


class Song(BaseModel):
    name: str
    version: Optional[str] = None
    features: Optional[str] = None
    notes: Optional[str] = None
    length: Optional[str] = None
    extra: dict = Field(default_factory=dict)


class Era(BaseModel):
    name: str
    songs: list[Song] = Field(default_factory=list)


class Sheet(BaseModel):
    name: str
    eras: list[Era] = Field(default_factory=list)


class SpreadsheetResult(BaseModel):
    spreadsheet_id: str
    url: str
    sheets: list[Sheet] = Field(default_factory=list)
