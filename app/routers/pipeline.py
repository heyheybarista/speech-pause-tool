import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import Session, Utterance, GlobalSetting
from app.schemas import CreateSessionRequest, CreateSessionResponse
from app.auth import verify_pipeline_token
from app.utils import (
    generate_token, parse_easyturn, DEFAULT_ANNOTATABLE_LABELS,
    DEFAULT_INSTRUCTION, LEGACY_DEFAULT_INSTRUCTION,
    is_annotatable_pause, is_annotatable_pause_ms, remove_short_pause_tags,
)

router = APIRouter()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@router.post("/pipeline/sessions", response_model=CreateSessionResponse, dependencies=[Depends(verify_pipeline_token)])
async def create_session(req: CreateSessionRequest, db: AsyncSession = Depends(get_db)):
    # Request values override the global defaults; an empty list is intentional.
    setting_rows = (await db.execute(
        select(GlobalSetting).where(
            GlobalSetting.key.in_(["instruction_text", "annotatable_labels"])
        )
    )).scalars().all()
    settings = {row.key: row.value for row in setting_rows}
    annotatable = (
        req.annotatable_labels
        if req.annotatable_labels is not None
        else settings.get("annotatable_labels", DEFAULT_ANNOTATABLE_LABELS)
    )
    instruction = settings.get("instruction_text", DEFAULT_INSTRUCTION)
    if instruction == LEGACY_DEFAULT_INSTRUCTION:
        instruction = DEFAULT_INSTRUCTION

    session = Session(
        id=_new_id(),
        external_participant_id=req.external_participant_id,
        title=req.title,
        status="speaker_review",
        access_token=generate_token(),
        annotatable_labels=annotatable,
        pipeline_meta=req.pipeline_meta,
        instruction_snapshot=instruction,
    )
    db.add(session)

    for u in req.utterances:
        # 解析 EasyTurn 标签（若 raw_text 中有标签而 easyturn_label 未显式给出）
        label = u.easyturn_label
        text = u.text
        raw_text = remove_short_pause_tags(u.raw_text) if u.raw_text else u.raw_text
        if raw_text and not label:
            parsed_text, parsed_label = parse_easyturn(raw_text)
            if parsed_label:
                text, label = parsed_text, parsed_label

        extra = dict(u.extra or {})
        pause_items = []
        for pause in (u.pauses or []):
            if not is_annotatable_pause(pause.duration):
                continue
            item = pause.model_dump(exclude_none=True)
            item.pop("level", None)
            pause_items.append(item)
        if not pause_items:
            legacy_pauses = extra.get("pauses", [])
            if isinstance(legacy_pauses, list):
                pause_items = []
                for item in legacy_pauses:
                    if not isinstance(item, dict) or not is_annotatable_pause(item.get("duration")):
                        continue
                    normalized = dict(item)
                    normalized.pop("level", None)
                    pause_items.append(normalized)
        if pause_items:
            # Persist the canonical pause list even when it arrived through the
            # legacy extra.pauses field so exports remain self-contained.
            extra["pauses"] = pause_items
        if (
            u.pause_duration_ms is not None
            and is_annotatable_pause_ms(u.pause_duration_ms)
        ):
            extra["pause_duration_ms"] = u.pause_duration_ms

        utterance = Utterance(
            id=_new_id(),
            session_id=session.id,
            seq=u.seq,
            speaker=u.speaker,
            text=text,
            raw_text=raw_text,
            easyturn_label=label,
            start_ms=u.start_ms,
            end_ms=u.end_ms,
            duration_ms=u.duration_ms,
            extra=extra or None,
        )
        db.add(utterance)

    await db.commit()

    from app.config import get_settings
    app_settings = get_settings()
    base = app_settings.public_base_url.rstrip("/")

    return CreateSessionResponse(
        session_id=session.id,
        access_token=None,
        participant_url=None,
        admin_url=f"{base}/admin-detail.html?id={session.id}",
        target_count=0,
        status=session.status,
    )
