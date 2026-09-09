"""Pydantic schemas for API requests and responses."""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

PROJECT_STATUSES = ("active", "archived", "done")
KNOWLEDGE_TYPES = ("text", "voice", "screenshot", "project_note")


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=4000)
    status: str = "active"

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty after strip")
        return v

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in PROJECT_STATUSES:
            raise ValueError(f"status must be one of {PROJECT_STATUSES}")
        return v


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=4000)
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in PROJECT_STATUSES:
            raise ValueError(f"status must be one of {PROJECT_STATUSES}")
        return v


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    status: str
    created_at: str
    updated_at: str


class ProjectContextAppend(BaseModel):
    content: str = Field(..., min_length=1, max_length=8000)
    title: Optional[str] = Field(None, max_length=200)
    source: str = Field("agent", max_length=60)


class KnowledgeCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field("", max_length=50000)
    type: str = "text"
    project_id: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
    source: str = Field("manual", max_length=60)

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if v not in KNOWLEDGE_TYPES:
            raise ValueError(f"type must be one of {KNOWLEDGE_TYPES}")
        return v

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title cannot be empty after strip")
        return v


class KnowledgeUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = Field(None, max_length=50000)
    type: Optional[str] = None
    project_id: Optional[int] = None
    tags: Optional[List[str]] = None
    source: Optional[str] = Field(None, max_length=60)
    summary: Optional[str] = Field(None, max_length=4000)

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in KNOWLEDGE_TYPES:
            raise ValueError(f"type must be one of {KNOWLEDGE_TYPES}")
        return v


class AttachmentOut(BaseModel):
    id: int
    knowledge_id: int
    filename: str
    mime_type: str
    size_bytes: int
    url: str
    created_at: str


class KnowledgeOut(BaseModel):
    id: int
    project_id: Optional[int]
    project_name: Optional[str] = None
    type: str
    title: str
    content: str
    source: str
    tags: List[str]
    summary: Optional[str]
    created_at: str
    updated_at: str
    attachments: List[AttachmentOut] = Field(default_factory=list)


class KnowledgeListItem(KnowledgeOut):
    attachments: List[AttachmentOut] = Field(default_factory=list)
    content_preview: str = ""


class SearchHit(KnowledgeOut):
    score: float = 0.0


class SummarizeRequest(BaseModel):
    knowledge_id: int
    fallback: bool = True


class SuggestTagsRequest(BaseModel):
    knowledge_id: int
    apply: bool = False
    fallback: bool = True


class LLMStatusOut(BaseModel):
    llm: dict
    stt: dict


class LogicGroupItem(BaseModel):
    id: int
    title: str
    excerpt: str


class LogicGroupsRequest(BaseModel):
    items: List[LogicGroupItem]
    context: Optional[str] = None


class PatternItem(BaseModel):
    id: int
    pattern: str
    where: str = ""


class MatchPatternsRequest(BaseModel):
    patterns: List[PatternItem]


class DecideRequest(BaseModel):
    verdict: str
    note: Optional[str] = None
    by: str = "human"


class RubricCriteriaRequest(BaseModel):
    criteria: str
