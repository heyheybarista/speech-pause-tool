from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings
from app.sqlite_migrations import migrate_annotation_categories, migrate_annotation_targets

settings = get_settings()
# SQLite with aiosqlite, WAL mode
DATABASE_URL = f"sqlite+aiosqlite:///{settings.database_path}"

engine = create_async_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    import app.models  # noqa: ensure all models loaded
    migrate_annotation_targets(settings.database_path)
    migrate_annotation_categories(settings.database_path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Enable WAL and foreign keys for the connection used during startup.
    async with engine.connect() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")

    # Create demo session if it doesn't exist
    await create_demo_session_if_missing()


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_demo_session_if_missing():
    """Create a fixed demo session on startup if it doesn't exist"""
    from app.models import Session, Utterance, AnnotationTarget
    from app.utils import generate_token
    from app.config import get_settings

    settings = get_settings()

    async with AsyncSessionLocal() as db:
        # Check if demo session already exists (by external_participant_id)
        from sqlalchemy import select
        result = await db.execute(
            select(Session).where(Session.external_participant_id == "DEMO001")
        )
        existing = result.scalar_one_or_none()

        if existing:
            return  # Demo session already exists

        # Create demo session
        token = generate_token()
        demo_session = Session(
            external_participant_id="DEMO001",
            title="【演示会话】口语任务",
            access_token=token,
            instruction_snapshot="请根据每个标记填写停顿原因，包括原因类别、心理过程描述和置信度。",
            status="created",
            annotatable_labels=["incomplete", "wait"]
        )
        db.add(demo_session)
        await db.flush()

        # Demo utterances data
        utterances_data = [
            {"seq": 1, "speaker": "experimenter", "text": "请你讲述一件你最近遇到的有趣的事情", "easyturn_label": "complete"},
            {"seq": 2, "speaker": "participant", "text": "嗯", "easyturn_label": "incomplete", "pause_duration_ms": 650},
            {"seq": 3, "speaker": "participant", "text": "最近我", "easyturn_label": "incomplete", "pause_duration_ms": 800},
            {"seq": 4, "speaker": "participant", "text": "去超市买东西的时候", "easyturn_label": "wait", "pause_duration_ms": 1200},
            {"seq": 5, "speaker": "participant", "text": "遇到了一只特别可爱的小狗", "easyturn_label": "complete"},
            {"seq": 6, "speaker": "experimenter", "text": "哦是吗，然后呢", "easyturn_label": "complete"},
            {"seq": 7, "speaker": "participant", "text": "那只狗", "easyturn_label": "incomplete", "pause_duration_ms": 700},
            {"seq": 8, "speaker": "participant", "text": "它一直跟着我", "easyturn_label": "wait", "pause_duration_ms": 900},
            {"seq": 9, "speaker": "participant", "text": "我就给它买了一些零食", "easyturn_label": "complete"},
            {"seq": 10, "speaker": "experimenter", "text": "听起来很有趣", "easyturn_label": "complete"}
        ]

        # Create utterances
        utterance_objs = {}
        for ut_data in utterances_data:
            utt = Utterance(
                session_id=demo_session.id,
                seq=ut_data["seq"],
                speaker=ut_data["speaker"],
                text=ut_data["text"],
                easyturn_label=ut_data.get("easyturn_label")
            )
            db.add(utt)
            await db.flush()  # Get the ID
            utterance_objs[ut_data["seq"]] = utt

        # Create annotation targets for annotatable labels
        annotatable_labels = ["incomplete", "wait"]
        for ut_data in utterances_data:
            label = ut_data.get("easyturn_label")
            if label in annotatable_labels:
                utt = utterance_objs[ut_data["seq"]]
                target = AnnotationTarget(
                    session_id=demo_session.id,
                    utterance_id=utt.id,
                    target_index=0,
                    label=label,
                    required=True,
                    pause_duration_ms=ut_data.get("pause_duration_ms")
                )
                db.add(target)

        await db.commit()

        participant_url = f"{settings.public_base_url}/a/{token}"
        print(f"✅ Demo session created: DEMO001")
        print(f"   Participant URL: {participant_url}")
