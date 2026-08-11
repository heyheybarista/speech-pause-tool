from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select
from app.database import get_db
from app.models import Session, Utterance, AnnotationTarget, Annotation
from app.schemas import ParticipantSessionOut, UtteranceOut, AnnotationTargetOut, PatchAnnotationRequest
from app.utils import (
    DEFAULT_INSTRUCTION, LABEL_HINTS, PHYSIOLOGICAL_PAUSE_CATEGORY,
    get_annotation_reason_categories, is_legacy_default_instruction,
    normalize_reason_categories,
)

router = APIRouter(tags=["participant"])


def _ensure_speaker_review_complete(session: Session):
    if session.status == "speaker_review":
        raise HTTPException(
            status_code=409,
            detail="The experimenter has not finished speaker review",
        )


def _build_target_out(target: AnnotationTarget) -> dict:
    """Build the annotation target output dict (including the nested annotation if any)."""
    ann = target.annotation
    categories = (
        get_annotation_reason_categories(ann.category, ann.categories)
        if ann else []
    )
    return {
        "id": target.id,
        "utterance_id": target.utterance_id,
        "target_index": target.target_index,
        "label": target.label,
        "required": target.required,
        "display_hint": target.display_hint or LABEL_HINTS.get(target.label, target.label),
        "pause_duration_ms": target.pause_duration_ms,
        "annotation": {
            "category": categories[0] if categories else None,
            "categories": categories,
            "description": ann.description,
            "confidence": ann.confidence,
            "is_complete": ann.is_complete,
        } if ann else None,
    }


@router.get("/a/{token}")
async def get_participant_session(token: str, db: AsyncSession = Depends(get_db)):
    """Load a participant session by access token, returning utterances with annotation targets.

    First access transitions session status from "created" to "in_progress".
    """
    stmt = (
        select(Session)
        .where(Session.access_token == token)
        .options(
            selectinload(Session.utterances)
            .selectinload(Utterance.annotation_targets)
            .selectinload(AnnotationTarget.annotation)
        )
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_speaker_review_complete(session)

    instruction = session.instruction_snapshot
    instruction_changed = is_legacy_default_instruction(instruction)
    if instruction_changed:
        instruction = DEFAULT_INSTRUCTION
        session.instruction_snapshot = instruction

    # First access transitions from "created" to "in_progress"
    was_created = session.status == "created"
    if session.status == "created":
        session.status = "in_progress"
        session.opened_at = datetime.now(timezone.utc)
    if instruction_changed or was_created:
        await db.commit()
    if was_created:
        await db.refresh(session)

    utterances_out = []
    for u in session.utterances:
        targets_out = []
        for tgt in u.annotation_targets:
            targets_out.append(_build_target_out(tgt))

        # pause_duration_ms 取第一个 target 的值（兼容旧逻辑）
        first_pause_ms = targets_out[0]["pause_duration_ms"] if targets_out else None

        utterances_out.append(UtteranceOut(
            id=u.id,
            seq=u.seq,
            speaker=u.speaker,
            text=u.text,
            raw_text=u.raw_text,
            easyturn_label=u.easyturn_label,
            start_ms=u.start_ms,
            end_ms=u.end_ms,
            duration_ms=u.duration_ms,
            pause_duration_ms=first_pause_ms,
            annotation_targets=targets_out,
        ))

    return ParticipantSessionOut(
        session_id=session.id,
        title=session.title,
        status=session.status,
        instruction=instruction,
        utterances=utterances_out,
    )


@router.patch("/a/{token}/annotations/{target_id}")
async def patch_annotation(
    token: str,
    target_id: str,
    body: PatchAnnotationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Upsert a partial annotation for a target. Only the fields sent in the body are updated.

    Returns the updated completion status (is_complete = True when all three
    of category, description, and confidence have values).
    """
    # Find session by token
    stmt = select(Session).where(Session.access_token == token)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_speaker_review_complete(session)
    if session.status == "submitted":
        raise HTTPException(status_code=400, detail="Session already submitted")

    # Find target belonging to this session
    tgt_stmt = (
        select(AnnotationTarget)
        .where(
            AnnotationTarget.id == target_id,
            AnnotationTarget.session_id == session.id,
        )
        .options(selectinload(AnnotationTarget.annotation))
    )
    result = await db.execute(tgt_stmt)
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")

    # Upsert annotation row
    if target.annotation:
        ann = target.annotation
    else:
        ann = Annotation(target_id=target.id)
        db.add(ann)

    # Apply only explicitly-provided fields (exclude_unset=True)
    updates = body.model_dump(exclude_unset=True)
    if "categories" in updates:
        categories = normalize_reason_categories(updates["categories"])
        if len(categories) > 2:
            raise HTTPException(status_code=422, detail="Select at most two reasons")
        ann.categories = categories or None
        ann.category = categories[0] if categories else None
    elif "category" in updates:
        categories = normalize_reason_categories(updates["category"])
        ann.categories = categories or None
        ann.category = categories[0] if categories else None
    else:
        categories = get_annotation_reason_categories(ann.category, ann.categories)

    if PHYSIOLOGICAL_PAUSE_CATEGORY in categories:
        ann.description = None
        ann.confidence = None
        ann.is_complete = True
    else:
        if "description" in updates:
            ann.description = updates["description"]
        if "confidence" in updates:
            ann.confidence = updates["confidence"]

        # Recompute completion: True when all three fields have values
        ann.is_complete = bool(categories and ann.description and ann.confidence)
    ann.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(ann)
    return {"ok": True, "is_complete": ann.is_complete}


@router.post("/a/{token}/submit")
async def submit_session(token: str, db: AsyncSession = Depends(get_db)):
    """Submit a session after verifying all required targets have complete annotations.

    If any required target is missing a complete annotation, returns 400
    with a list of incomplete target_ids.
    """
    stmt = (
        select(Session)
        .where(Session.access_token == token)
        .options(
            selectinload(Session.annotation_targets).selectinload(AnnotationTarget.annotation)
        )
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_speaker_review_complete(session)
    if session.status == "submitted":
        return {"ok": True, "message": "Already submitted"}

    # Validate all required targets have complete annotations
    incomplete = []
    for t in session.annotation_targets:
        if t.required:
            ann = t.annotation
            if not ann or not ann.is_complete:
                incomplete.append({
                    "target_id": t.id,
                    "display_hint": t.display_hint or t.label,
                })

    if incomplete:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Not all required targets are complete",
                "incomplete": incomplete,
            },
        )

    session.status = "submitted"
    session.submitted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "message": "Submitted"}
