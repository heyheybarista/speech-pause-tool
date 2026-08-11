import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Text, Boolean, DateTime, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.orm import relationship
from app.database import Base


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Experimenter(Base):
    __tablename__ = "experimenters"
    id = Column(String(24), primary_key=True, default=_new_id)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(16), nullable=False, default="experimenter")  # admin | experimenter
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)


class Session(Base):
    __tablename__ = "sessions"
    id = Column(String(24), primary_key=True, default=_new_id)
    external_participant_id = Column(String(64), nullable=True)
    title = Column(String(256), nullable=True)
    # speaker_review | created | in_progress | submitted
    status = Column(String(20), nullable=False, default="created")
    access_token = Column(String(64), unique=True, nullable=False, index=True)
    annotatable_labels = Column(JSON, nullable=False, default=list)
    pipeline_meta = Column(JSON, nullable=True)
    instruction_snapshot = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    opened_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)

    utterances = relationship("Utterance", back_populates="session", order_by="Utterance.seq",
                              cascade="all, delete-orphan")
    annotation_targets = relationship("AnnotationTarget", back_populates="session",
                                      cascade="all, delete-orphan")


class Utterance(Base):
    __tablename__ = "utterances"
    id = Column(String(24), primary_key=True, default=_new_id)
    session_id = Column(String(24), ForeignKey("sessions.id"), nullable=False)
    seq = Column(Integer, nullable=False)
    speaker = Column(String(20), nullable=False)  # participant | experimenter
    text = Column(Text, nullable=False)
    raw_text = Column(Text, nullable=True)
    easyturn_label = Column(String(20), nullable=True)
    start_ms = Column(Integer, nullable=True)
    end_ms = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    extra = Column(JSON, nullable=True)

    session = relationship("Session", back_populates="utterances")
    annotation_targets = relationship(
        "AnnotationTarget",
        back_populates="utterance",
        order_by=lambda: (AnnotationTarget.target_index, AnnotationTarget.id),
        cascade="all, delete-orphan",
    )


class AnnotationTarget(Base):
    __tablename__ = "annotation_targets"
    id = Column(String(24), primary_key=True, default=_new_id)
    session_id = Column(String(24), ForeignKey("sessions.id"), nullable=False)
    utterance_id = Column(String(24), ForeignKey("utterances.id"), nullable=False)
    target_index = Column(Integer, nullable=False, default=0)
    label = Column(String(20), nullable=False)
    required = Column(Boolean, default=True)
    display_hint = Column(String(64), nullable=True)
    pause_duration_ms = Column(Integer, nullable=True)

    session = relationship("Session", back_populates="annotation_targets")
    utterance = relationship("Utterance", back_populates="annotation_targets")
    annotation = relationship("Annotation", back_populates="target", uselist=False,
                              cascade="all, delete-orphan")


class Annotation(Base):
    __tablename__ = "annotations"
    id = Column(String(24), primary_key=True, default=_new_id)
    target_id = Column(String(24), ForeignKey("annotation_targets.id"), nullable=False, unique=True)
    category = Column(String(32), nullable=True)
    categories = Column(JSON, nullable=True)
    description = Column(Text, nullable=True)
    confidence = Column(Integer, nullable=True)
    is_complete = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    target = relationship("AnnotationTarget", back_populates="annotation")


class GlobalSetting(Base):
    __tablename__ = "global_settings"
    key = Column(String(64), primary_key=True)
    value = Column(JSON, nullable=False)
