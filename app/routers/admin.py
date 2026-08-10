import csv
import io
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, delete
import bcrypt
from app.database import get_db
from app.models import Session, Utterance, AnnotationTarget, Annotation, Experimenter, GlobalSetting
from app.schemas import (
    AdminLoginRequest, SessionListItem, SettingsUpdate, SettingsOut,
    SpeakerReviewRequest, UserCreate, UserOut, UserPasswordReset,
)
from app.auth import get_current_user, require_admin, ADMIN_SESSION_KEY
from app.utils import (
    generate_token, DEFAULT_INSTRUCTION, DEFAULT_ANNOTATABLE_LABELS,
    DEFAULT_REASON_CATEGORIES, LABEL_HINTS, LEGACY_DEFAULT_INSTRUCTION,
    is_legacy_default_reason_categories, is_annotatable_pause,
    is_annotatable_pause_ms, remove_last_annotatable_pause_tag,
    extract_annotatable_pause_items,
    PHYSIOLOGICAL_PAUSE_REASON, PHYSIOLOGICAL_PAUSE_CATEGORY,
    OTHER_REASON_LABEL,
)

router = APIRouter(tags=["admin"])


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ── helpers ────────────────────────────────────────────────

async def _get_settings(db: AsyncSession) -> dict:
    """读取或初始化全局设置"""
    rows = (await db.execute(select(GlobalSetting))).scalars().all()
    store = {r.key: r.value for r in rows}
    if "instruction_text" not in store or store["instruction_text"] == LEGACY_DEFAULT_INSTRUCTION:
        store["instruction_text"] = DEFAULT_INSTRUCTION
    if "annotatable_labels" not in store:
        store["annotatable_labels"] = DEFAULT_ANNOTATABLE_LABELS
    if (
        "reason_categories" not in store
        or is_legacy_default_reason_categories(store["reason_categories"])
    ):
        store["reason_categories"] = list(DEFAULT_REASON_CATEGORIES)
    elif isinstance(store["reason_categories"], list) and not any(
        isinstance(item, dict) and item.get("value") == PHYSIOLOGICAL_PAUSE_CATEGORY
        for item in store["reason_categories"]
    ):
        store["reason_categories"] = [
            *store["reason_categories"],
            dict(PHYSIOLOGICAL_PAUSE_REASON),
        ]
    if isinstance(store["reason_categories"], list):
        store["reason_categories"] = [
            {
                **item,
                "label": OTHER_REASON_LABEL,
            }
            if isinstance(item, dict)
            and item.get("value") == "other"
            and item.get("label") == "其他"
            else item
            for item in store["reason_categories"]
        ]
    return store


async def _init_admin(db: AsyncSession):
    """确保至少有一个 admin。无则创 admin/admin。"""
    existing = (await db.execute(select(Experimenter))).scalars().first()
    if not existing:
        pw = bcrypt.hashpw("admin".encode(), bcrypt.gensalt()).decode()
        db.add(Experimenter(id=_new_id(), username="admin", password_hash=pw, role="admin"))
        await db.commit()


def _create_targets_for_utterance(session: Session, utterance: Utterance) -> list[AnnotationTarget]:
    """Rebuild pause targets after the experimenter confirms speakers."""
    extra = utterance.extra if isinstance(utterance.extra, dict) else {}
    pauses = extra.get("pauses")
    if isinstance(pauses, list) and pauses:
        targets = []
        for pause in pauses:
            if not isinstance(pause, dict):
                continue
            try:
                duration = float(pause.get("duration", 0))
            except (TypeError, ValueError):
                continue
            if not is_annotatable_pause(duration):
                continue
            targets.append(AnnotationTarget(
                id=_new_id(),
                session_id=session.id,
                utterance_id=utterance.id,
                target_index=len(targets),
                label="pause",
                required=True,
                display_hint=f"停顿 {duration:.2f}s",
                pause_duration_ms=int(duration * 1000),
            ))
        return targets

    label = utterance.easyturn_label
    pause_duration_ms = extra.get("pause_duration_ms")
    if (
        label
        and label in (session.annotatable_labels or [])
        and (
            pause_duration_ms is None
            or is_annotatable_pause_ms(pause_duration_ms)
        )
    ):
        return [AnnotationTarget(
            id=_new_id(),
            session_id=session.id,
            utterance_id=utterance.id,
            target_index=0,
            label=label,
            required=True,
            display_hint=LABEL_HINTS.get(label, label),
            pause_duration_ms=pause_duration_ms,
        )]
    return []


def _remove_last_pause_from_utterance(utterance: Utterance) -> None:
    """Remove the final eligible pause from a participant utterance."""
    extra = dict(utterance.extra) if isinstance(utterance.extra, dict) else {}
    pauses = extra.get("pauses")
    removed_from_list = False

    if isinstance(pauses, list):
        remaining = list(pauses)
        for index in range(len(remaining) - 1, -1, -1):
            pause = remaining[index]
            if isinstance(pause, dict) and is_annotatable_pause(pause.get("duration")):
                remaining.pop(index)
                removed_from_list = True
                break
        if remaining:
            extra["pauses"] = remaining
            durations = [
                float(pause.get("duration"))
                for pause in remaining
                if isinstance(pause, dict)
                and is_annotatable_pause(pause.get("duration"))
            ]
            if durations:
                extra["pause_duration_ms"] = int(max(durations) * 1000)
            else:
                extra.pop("pause_duration_ms", None)
        else:
            extra.pop("pauses", None)
            extra.pop("pause_duration_ms", None)

    original_raw_text = utterance.raw_text or ""
    updated_raw_text = remove_last_annotatable_pause_tag(original_raw_text)
    removed_from_text = updated_raw_text != original_raw_text
    if removed_from_text:
        utterance.raw_text = updated_raw_text

    if removed_from_list or removed_from_text:
        if removed_from_text and not isinstance(pauses, list):
            remaining = extract_annotatable_pause_items(updated_raw_text)
            if remaining:
                extra["pauses"] = remaining
                extra["pause_duration_ms"] = int(
                    max(item["duration"] for item in remaining) * 1000
                )
            else:
                # Prevent the legacy label fallback from recreating the removed pause.
                extra["pause_duration_ms"] = 0
        elif removed_from_list and not extra.get("pauses"):
            # The structured list may have contained the only eligible pause.
            extra["pause_duration_ms"] = 0
        utterance.extra = extra or None


# ── login / logout ─────────────────────────────────────────

@router.post("/admin/login")
async def admin_login(body: AdminLoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    await _init_admin(db)
    stmt = select(Experimenter).where(Experimenter.username == body.username, Experimenter.is_active == True)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user or not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    request.session[ADMIN_SESSION_KEY] = user.id
    return {"ok": True, "username": user.username, "role": user.role}


@router.post("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/admin/me")
async def admin_me(user: Experimenter = Depends(get_current_user)):
    return {"username": user.username, "role": user.role}


# ── sessions ───────────────────────────────────────────────

@router.get("/admin/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: Experimenter = Depends(get_current_user),
):
    stmt = (
        select(Session)
        .options(selectinload(Session.annotation_targets).selectinload(AnnotationTarget.annotation))
        .order_by(Session.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    items = []
    for s in rows:
        total = len(s.annotation_targets)
        done = sum(1 for t in s.annotation_targets if t.annotation and t.annotation.is_complete)
        items.append(SessionListItem(
            id=s.id,
            external_participant_id=s.external_participant_id,
            title=s.title,
            status=s.status,
            target_count=total,
            completed_count=done,
            created_at=s.created_at,
            submitted_at=s.submitted_at,
        ))
    return items


@router.get("/admin/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: Experimenter = Depends(get_current_user),
):
    stmt = (
        select(Session)
        .where(Session.id == session_id)
        .options(
            selectinload(Session.utterances).selectinload(Utterance.annotation_targets).selectinload(AnnotationTarget.annotation)
        )
    )
    s = (await db.execute(stmt)).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")

    utterances = []
    for u in s.utterances:
        targets = []
        for t in u.annotation_targets:
            ann = t.annotation
            targets.append({
                "id": t.id,
                "target_index": t.target_index,
                "label": t.label,
                "required": t.required,
                "display_hint": t.display_hint,
                "pause_duration_ms": t.pause_duration_ms,
                "annotation": {
                    "category": ann.category,
                    "description": ann.description,
                    "confidence": ann.confidence,
                    "is_complete": ann.is_complete,
                } if ann else None,
            })
        utterances.append({
            "id": u.id,
            "seq": u.seq,
            "speaker": u.speaker,
            "text": u.text,
            "raw_text": u.raw_text,
            "easyturn_label": u.easyturn_label,
            "targets": targets,
        })

    from app.config import get_settings
    base = get_settings().public_base_url.rstrip("/")

    is_speaker_review = s.status == "speaker_review"
    return {
        "session": {
            "id": s.id,
            "external_participant_id": s.external_participant_id,
            "title": s.title,
            "status": s.status,
            "access_token": None if is_speaker_review else s.access_token,
            "participant_url": None if is_speaker_review else f"{base}/a/{s.access_token}",
            "instruction_snapshot": s.instruction_snapshot,
            "created_at": s.created_at.isoformat(),
            "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
        },
        "utterances": utterances,
    }


@router.post("/admin/sessions/{session_id}/speaker-review")
async def confirm_speaker_review(
    session_id: str,
    body: SpeakerReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: Experimenter = Depends(get_current_user),
):
    stmt = (
        select(Session)
        .where(Session.id == session_id)
        .options(selectinload(Session.utterances))
    )
    s = (await db.execute(stmt)).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    if s.status != "speaker_review":
        raise HTTPException(status_code=409, detail="Speaker review is already complete")

    submitted_ids = [item.utterance_id for item in body.utterances]
    expected_ids = {utterance.id for utterance in s.utterances}
    if len(submitted_ids) != len(set(submitted_ids)):
        raise HTTPException(status_code=422, detail="Each utterance must be submitted exactly once")
    if set(submitted_ids) != expected_ids:
        raise HTTPException(status_code=422, detail="Speaker review must include every utterance")

    speaker_by_id = {item.utterance_id: item.speaker for item in body.utterances}
    existing_targets = (await db.execute(
        select(AnnotationTarget).where(AnnotationTarget.session_id == session_id)
    )).scalars().all()
    for target in existing_targets:
        await db.execute(delete(Annotation).where(Annotation.target_id == target.id))
    await db.execute(delete(AnnotationTarget).where(AnnotationTarget.session_id == session_id))

    for utterance in s.utterances:
        utterance.speaker = speaker_by_id[utterance.id]

    # A pause immediately before a confirmed experimenter turn belongs to the
    # turn transition rather than the participant's annotatable speech.
    for index, utterance in enumerate(s.utterances[:-1]):
        next_utterance = s.utterances[index + 1]
        if (
            utterance.speaker == "participant"
            and next_utterance.speaker == "experimenter"
        ):
            _remove_last_pause_from_utterance(utterance)

    target_count = 0
    for utterance in s.utterances:
        if utterance.speaker != "participant":
            continue
        targets = _create_targets_for_utterance(s, utterance)
        db.add_all(targets)
        target_count += len(targets)

    s.access_token = generate_token()
    s.status = "created"
    await db.commit()

    from app.config import get_settings
    base = get_settings().public_base_url.rstrip("/")
    return {
        "ok": True,
        "status": s.status,
        "access_token": s.access_token,
        "participant_url": f"{base}/a/{s.access_token}",
        "target_count": target_count,
    }


@router.post("/admin/sessions/{session_id}/reset")
async def reset_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: Experimenter = Depends(get_current_user),
):
    s = (await db.execute(select(Session).where(Session.id == session_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    if s.status == "speaker_review":
        raise HTTPException(status_code=409, detail="Complete speaker review before resetting")
    # 删除已有 annotation
    targets = (await db.execute(
        select(AnnotationTarget).where(AnnotationTarget.session_id == session_id)
    )).scalars().all()
    for t in targets:
        await db.execute(delete(Annotation).where(Annotation.target_id == t.id))
    s.status = "in_progress"
    s.submitted_at = None
    s.opened_at = None
    await db.commit()
    return {"ok": True, "status": s.status}


@router.delete("/admin/sessions/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: Experimenter = Depends(get_current_user),
):
    """永久删除一场会话及其话语、标注目标与填写内容。"""
    s = (await db.execute(select(Session).where(Session.id == session_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")

    targets = (await db.execute(
        select(AnnotationTarget).where(AnnotationTarget.session_id == session_id)
    )).scalars().all()
    for t in targets:
        await db.execute(delete(Annotation).where(Annotation.target_id == t.id))
    await db.execute(delete(AnnotationTarget).where(AnnotationTarget.session_id == session_id))
    await db.execute(delete(Utterance).where(Utterance.session_id == session_id))
    await db.execute(delete(Session).where(Session.id == session_id))
    await db.commit()
    return {"ok": True, "deleted": session_id}


@router.get("/admin/sessions/{session_id}/export")
async def export_session(
    session_id: str,
    format: str = Query("json"),
    db: AsyncSession = Depends(get_db),
    user: Experimenter = Depends(get_current_user),
):
    s = (await db.execute(
        select(Session).where(Session.id == session_id).options(
            selectinload(Session.utterances).selectinload(Utterance.annotation_targets).selectinload(AnnotationTarget.annotation)
        )
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")

    rows = []
    for u in s.utterances:
        targets = u.annotation_targets or [None]
        for t in targets:
            ann = t.annotation if t else None
            rows.append({
                "session_id": s.id,
                "external_participant_id": s.external_participant_id,
                "seq": u.seq,
                "speaker": u.speaker,
                "text": u.text,
                "raw_text": u.raw_text,
                "easyturn_label": u.easyturn_label,
                "target_index": t.target_index if t else None,
                "pause_duration_ms": t.pause_duration_ms if t else None,
                "target_label": t.label if t else None,
                "display_hint": t.display_hint if t else None,
                "category": ann.category if ann else None,
                "description": ann.description if ann else None,
                "confidence": ann.confidence if ann else None,
                "is_complete": ann.is_complete if ann else False,
            })

    if format == "csv":
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return Response(content=output.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=session_{session_id}.csv"})

    return {
        "session_id": s.id,
        "external_participant_id": s.external_participant_id,
        "status": s.status,
        "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
        "instruction_snapshot": s.instruction_snapshot,
        "items": rows,
    }


# ── settings ──────────────────────────────────────────
# GET requires NO auth — the participant page needs to load reason_categories
@router.get("/admin/settings")
async def get_settings(db: AsyncSession = Depends(get_db)):
    s = await _get_settings(db)
    return SettingsOut(**s)


@router.put("/admin/settings")
async def update_settings(body: SettingsUpdate, user: Experimenter = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    store = await _get_settings(db)
    if body.instruction_text is not None:
        store["instruction_text"] = body.instruction_text
    if body.annotatable_labels is not None:
        store["annotatable_labels"] = body.annotatable_labels
        # 同时把当前全局默认作为新会话默认——不影响已创建的会话
    if body.reason_categories is not None:
        store["reason_categories"] = body.reason_categories

    for key, val in store.items():
        existing = (await db.execute(select(GlobalSetting).where(GlobalSetting.key == key))).scalar_one_or_none()
        if existing:
            existing.value = val
        else:
            db.add(GlobalSetting(key=key, value=val))
    await db.commit()
    return SettingsOut(**store)


# ── users (admin only) ─────────────────────────────────────

@router.get("/admin/users")
async def list_users(user: Experimenter = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Experimenter).order_by(Experimenter.created_at))).scalars().all()
    return [UserOut(id=r.id, username=r.username, role=r.role, is_active=r.is_active, created_at=r.created_at) for r in rows]


@router.post("/admin/users")
async def create_user(body: UserCreate, user: Experimenter = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(Experimenter).where(Experimenter.username == body.username))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    pw = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    new_user = Experimenter(id=_new_id(), username=body.username, password_hash=pw, role=body.role)
    db.add(new_user)
    await db.commit()
    return UserOut(id=new_user.id, username=new_user.username, role=new_user.role, is_active=True, created_at=new_user.created_at)


@router.put("/admin/users/{user_id}")
async def toggle_user_active(user_id: str, user: Experimenter = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    target = (await db.execute(select(Experimenter).where(Experimenter.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Not found")
    target.is_active = not target.is_active
    await db.commit()
    return {"ok": True, "is_active": target.is_active}


@router.post("/admin/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, body: UserPasswordReset, user: Experimenter = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    target = (await db.execute(select(Experimenter).where(Experimenter.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Not found")
    target.password_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
    await db.commit()
    return {"ok": True}
