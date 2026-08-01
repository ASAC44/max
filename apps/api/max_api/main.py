import hmac
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent import parse_request
from .config import admin_token, agent_mode, web_origin
from .db import SessionLocal, get_session
from .models import Event, ExternalAttempt, Mission
from .schemas import (
    ApprovalView,
    ApproveCommand,
    AttemptView,
    CheckoutView,
    CommandBase,
    MissionCreate,
    MissionReply,
    MissionView,
    RequoteCommand,
)
from .workflow import (
    WorkflowError,
    apply_intent,
    approve_quote,
    cancel,
    command_failed,
    create_mission,
    finalize_checkout,
    package_ready,
    preflight_command,
    record_agent_failure,
    recover_in_progress_attempts,
    requote,
    run_robot_simulation,
    simulate_checkout,
    start_checkout_attempt,
    start_staged_fulfilment,
)

bearer = HTTPBearer(auto_error=False)


def interpretation_error(mission_id: str) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={"message": "request interpretation failed", "mission_id": mission_id},
    )


async def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    expected = admin_token()
    if not expected:
        raise HTTPException(status_code=503, detail="MAX_ADMIN_TOKEN is not configured")
    if not credentials or credentials.scheme.lower() != "bearer" or not hmac.compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=401, detail="invalid operator credential")


def mission_view(session: Session, mission: Mission) -> MissionView:
    events = session.scalars(select(Event).where(Event.mission_id == mission.id).order_by(Event.sequence)).all()
    attempts = session.scalars(select(ExternalAttempt).where(ExternalAttempt.mission_id == mission.id).order_by(ExternalAttempt.started_at)).all()
    attempt_views = [AttemptView.model_validate(attempt) for attempt in attempts]
    return MissionView(
        id=mission.id,
        parent_mission_id=mission.parent_mission_id,
        version=mission.version,
        phase=mission.phase,
        environment=mission.environment,
        agent_mode=mission.agent_mode,
        request_text=mission.request_text,
        intent=mission.intent,
        clarification_question=mission.clarification_question,
        quote=mission.quote,
        quote_hash=mission.quote_hash,
        commerce_status=mission.commerce_status,
        payment_status=mission.payment_status,
        checkout_status=mission.checkout_status,
        fulfilment_status=mission.fulfilment_status,
        notification_status=mission.notification_status,
        created_at=mission.created_at,
        updated_at=mission.updated_at,
        events=events,
        attempts=attempt_views,
        approval=ApprovalView(status=mission.payment_status, quote_hash=mission.approval_quote_hash),
        checkout=CheckoutView(status=mission.checkout_status, latest_attempt=attempt_views[-1] if attempt_views else None),
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with SessionLocal() as session:
        recover_in_progress_attempts(session)
    yield


app = FastAPI(title="Max API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[web_origin()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)


@app.exception_handler(WorkflowError)
async def workflow_error_handler(_request, exc: WorkflowError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "agent_mode": agent_mode(), "environment": "local"}


@app.post("/api/missions", response_model=MissionView, dependencies=[Depends(require_admin)])
async def create(
    body: MissionCreate,
    idempotency_key: str = Header(min_length=8, max_length=48, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
):
    mode = agent_mode()
    try:
        mission = create_mission(session, body.text, idempotency_key, mode)
    except WorkflowError as exc:
        active = session.scalar(select(Mission).where(Mission.active_slot == "active"))
        if str(exc) == "another mission is active" and active:
            raise HTTPException(
                status_code=409,
                detail={"message": str(exc), "mission_id": active.id},
            ) from exc
        raise
    if mission.phase != "DRAFT":
        return mission_view(session, mission)
    parse_command = f"{idempotency_key}-parse"
    parse_payload = {"text": body.text}
    if replay := preflight_command(
        session, mission.id, mission.version, parse_command, "initial_parse", parse_payload, {"DRAFT"}
    ):
        if command_failed(session, parse_command):
            raise interpretation_error(replay.id)
        return mission_view(session, replay)
    try:
        intent = await parse_request(body.text)
    except Exception as exc:
        failed = record_agent_failure(
            session,
            mission.id,
            mission.version,
            parse_command,
            "initial_parse",
            parse_payload,
            type(exc).__name__,
        )
        raise interpretation_error(failed.id) from exc
    mission = apply_intent(
        session,
        mission.id,
        mission.version,
        parse_command,
        intent,
        command_scope="initial_parse",
        command_payload=parse_payload,
    )
    return mission_view(session, mission)


@app.get("/api/missions/{mission_id}", response_model=MissionView, dependencies=[Depends(require_admin)])
async def get_mission(mission_id: str, session: Session = Depends(get_session)):
    mission = session.get(Mission, mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="mission not found")
    return mission_view(session, mission)


@app.post("/api/missions/{mission_id}/commands/reply", response_model=MissionView, dependencies=[Depends(require_admin)])
async def reply(mission_id: str, body: MissionReply, session: Session = Depends(get_session)):
    mission = session.get(Mission, mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="mission not found")
    command_payload = {"text": body.text, "expected_version": body.expected_version}
    if replay := preflight_command(
        session,
        mission_id,
        body.expected_version,
        body.command_id,
        "reply",
        command_payload,
        {"DRAFT", "NEEDS_CLARIFICATION"},
    ):
        if command_failed(session, body.command_id):
            raise interpretation_error(replay.id)
        return mission_view(session, replay)
    combined = f"{mission.request_text}\nOwner clarification: {body.text}"
    try:
        intent = await parse_request(combined)
    except Exception as exc:
        failed = record_agent_failure(
            session,
            mission_id,
            body.expected_version,
            body.command_id,
            "reply",
            command_payload,
            type(exc).__name__,
        )
        raise interpretation_error(failed.id) from exc
    mission = apply_intent(
        session,
        mission_id,
        body.expected_version,
        body.command_id,
        intent,
        combined,
        command_scope="reply",
        command_payload=command_payload,
    )
    return mission_view(session, mission)


@app.post("/api/missions/{mission_id}/commands/approve", response_model=MissionView, dependencies=[Depends(require_admin)])
async def approve(mission_id: str, body: ApproveCommand, session: Session = Depends(get_session)):
    mission = approve_quote(
        session,
        mission_id,
        body.expected_version,
        body.command_id,
        body.quote_hash,
        body.simulated_outcome,
    )
    if mission.phase in {"PAYMENT_DECLINED", "CHECKOUT_OUTCOME_UNKNOWN"}:
        return mission_view(session, mission)
    attempt_command = f"{body.command_id}-checkout"
    if mission.phase == "PAYMENT_PERMISSION_READY":
        attempt = start_checkout_attempt(session, mission_id, mission.version, attempt_command)
        mission = session.get(Mission, mission_id)
    elif mission.phase == "MERCHANT_CHECKOUT_IN_PROGRESS":
        attempt = session.scalar(
            select(ExternalAttempt).where(
                ExternalAttempt.mission_id == mission_id,
                ExternalAttempt.command_id == attempt_command,
            )
        )
        if not attempt:
            raise HTTPException(status_code=409, detail="checkout attempt record is missing")
    else:
        raise HTTPException(status_code=409, detail="approval flow cannot continue from the current phase")
    result = simulate_checkout(body.simulated_outcome, attempt.id)
    mission = finalize_checkout(session, mission_id, mission.version, f"{body.command_id}-result", attempt.id, result)
    return mission_view(session, mission)


@app.post("/api/missions/{mission_id}/commands/requote", response_model=MissionView, dependencies=[Depends(require_admin)])
async def change_quote(mission_id: str, body: RequoteCommand, session: Session = Depends(get_session)):
    return mission_view(session, requote(session, mission_id, body.expected_version, body.command_id, body.amount_minor))


@app.post("/api/missions/{mission_id}/commands/cancel", response_model=MissionView, dependencies=[Depends(require_admin)])
async def cancel_mission(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    return mission_view(session, cancel(session, mission_id, body.expected_version, body.command_id))


@app.post("/api/missions/{mission_id}/commands/start-staged", response_model=MissionView, dependencies=[Depends(require_admin)])
async def start_staged(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    return mission_view(session, start_staged_fulfilment(session, mission_id, body.expected_version, body.command_id))


@app.post("/api/missions/{mission_id}/commands/package-ready", response_model=MissionView, dependencies=[Depends(require_admin)])
async def mark_package_ready(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    return mission_view(session, package_ready(session, mission_id, body.expected_version, body.command_id))


@app.post("/api/missions/{mission_id}/commands/run-robot", response_model=MissionView, dependencies=[Depends(require_admin)])
async def run_robot(mission_id: str, body: CommandBase, session: Session = Depends(get_session)):
    return mission_view(session, run_robot_simulation(session, mission_id, body.expected_version, body.command_id))
