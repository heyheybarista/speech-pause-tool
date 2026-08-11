from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime


# --- Pipeline Create Session ---

class PauseIn(BaseModel):
    duration: float = Field(ge=0)
    level: Optional[str] = None
    kind: Optional[str] = None
    position: Optional[int] = None
    position_in_clean_text: Optional[int] = None

    model_config = dict(extra="allow")


class UtteranceIn(BaseModel):
    seq: int
    speaker: str  # participant | experimenter
    text: str
    raw_text: Optional[str] = None
    easyturn_label: Optional[str] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    duration_ms: Optional[int] = None
    pause_duration_ms: Optional[int] = None
    pauses: list[PauseIn] = Field(default_factory=list)
    extra: Optional[dict] = None


class CreateSessionRequest(BaseModel):
    external_participant_id: Optional[str] = None
    title: Optional[str] = None
    annotatable_labels: Optional[list[str]] = None
    pipeline_meta: Optional[dict] = None
    utterances: list[UtteranceIn]


class CreateSessionResponse(BaseModel):
    session_id: str
    access_token: Optional[str] = None
    participant_url: Optional[str] = None
    admin_url: str
    target_count: int
    status: str


# --- Participant ---

class AnnotationTargetOut(BaseModel):
    id: str
    utterance_id: str
    target_index: Optional[int] = None
    label: str
    required: bool
    display_hint: Optional[str] = None
    pause_duration_ms: Optional[int] = None
    annotation: Optional[dict] = None  # {category, categories, description, confidence, is_complete}

    model_config = dict(from_attributes=True)


class UtteranceOut(BaseModel):
    id: str
    seq: int
    speaker: str
    text: str
    raw_text: Optional[str] = None  # 含 <PAUSE:x.xs> 标记的原始文本
    easyturn_label: Optional[str] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    duration_ms: Optional[int] = None
    pause_duration_ms: Optional[int] = None
    annotation_targets: list[AnnotationTargetOut] = Field(default_factory=list)

    model_config = dict(from_attributes=True)


class ParticipantSessionOut(BaseModel):
    session_id: str
    title: Optional[str]
    status: str
    instruction: Optional[str]
    utterances: list[UtteranceOut]


class PatchAnnotationRequest(BaseModel):
    category: Optional[str] = None
    categories: Optional[list[str]] = Field(default=None, max_length=2)
    description: Optional[str] = None
    confidence: Optional[int] = Field(default=None, ge=1, le=7)


# --- Admin ---

class SessionListItem(BaseModel):
    id: str
    external_participant_id: Optional[str]
    title: Optional[str]
    status: str
    target_count: int
    completed_count: int
    created_at: datetime
    submitted_at: Optional[datetime]


class SpeakerReviewItem(BaseModel):
    utterance_id: str
    speaker: Literal["participant", "experimenter"]


class SpeakerReviewRequest(BaseModel):
    utterances: list[SpeakerReviewItem]


class AdminLoginRequest(BaseModel):
    username: str
    password: str


# --- Settings ---

class SettingsUpdate(BaseModel):
    instruction_text: Optional[str] = None
    annotatable_labels: Optional[list[str]] = None
    reason_categories: Optional[list[dict]] = None  # [{value, label, hint}]


class SettingsOut(BaseModel):
    instruction_text: str
    annotatable_labels: list[str]
    reason_categories: list[dict]


# --- Users ---

class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    role: str = "experimenter"


class UserOut(BaseModel):
    id: str
    username: str
    role: str
    is_active: bool
    created_at: datetime


class UserPasswordReset(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)
