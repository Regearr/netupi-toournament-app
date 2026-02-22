from __future__ import annotations

import csv
import hashlib
import io
import random
from collections import defaultdict
from datetime import datetime

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.database import Base, engine, get_db
from app.models import (
    Announcement,
    Evaluation,
    EvaluationAssignment,
    Notification,
    Round,
    RoundStatus,
    ScheduleEvent,
    Submission,
    Team,
    TeamMember,
    Tournament,
    TournamentStatus,
    User,
    UserRole,
)

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Tournament Platform")
app.add_middleware(SessionMiddleware, secret_key="dev-secret")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def now() -> datetime:
    return datetime.utcnow()


def parse_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def hash_password(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def current_user(request: Request, db: Session) -> User | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    return db.query(User).filter(User.id == uid).first()


def require_auth(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(401, "Login required")
    return user


def require_admin(request: Request, db: Session) -> User:
    user = require_auth(request, db)
    if user.role != UserRole.admin:
        raise HTTPException(403, "Admin only")
    return user


def add_notification(db: Session, user_id: int, message: str):
    db.add(Notification(user_id=user_id, message=message))


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    status_filter = request.query_params.get("status")
    query = db.query(Tournament)
    if status_filter:
        query = query.filter(Tournament.status == TournamentStatus(status_filter))
    tournaments = query.order_by(Tournament.start_at.desc()).all()
    anns = db.query(Announcement).order_by(Announcement.created_at.desc()).limit(10).all()
    return templates.TemplateResponse("home.html", {"request": request, "tournaments": tournaments, "user": user, "announcements": anns})


@app.get("/auth/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/auth/register")
def register_user(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "Email already exists")
    user = User(email=email, password_hash=hash_password(password), role=UserRole.visitor)
    db.add(user)
    db.commit()
    return RedirectResponse("/auth/login", status_code=303)


@app.get("/auth/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/auth/login")
def login_user(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email, User.password_hash == hash_password(password)).first()
    if not user:
        raise HTTPException(401, "Invalid credentials")
    request.session["uid"] = user.id
    if not user.profile_completed:
        return RedirectResponse("/profile/edit", status_code=303)
    return RedirectResponse("/", status_code=303)


@app.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/profile/edit", response_class=HTMLResponse)
def edit_profile_page(request: Request, db: Session = Depends(get_db)):
    user = require_auth(request, db)
    return templates.TemplateResponse("profile_edit.html", {"request": request, "user": user})


@app.post("/profile/edit")
def edit_profile(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    school_name: str = Form(""),
    contact_info: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_auth(request, db)
    other = db.query(User).filter(User.email == email, User.id != user.id).first()
    if other:
        raise HTTPException(400, "Email already in use")
    user.full_name = full_name
    user.email = email
    user.school_name = school_name or None
    user.contact_info = contact_info or None
    user.profile_completed = True
    db.commit()
    return RedirectResponse(f"/profile/{user.id}", status_code=303)


@app.get("/profile/{user_id}", response_class=HTMLResponse)
def profile_page(user_id: int, request: Request, db: Session = Depends(get_db)):
    viewer = current_user(request, db)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404)
    notes = db.query(Notification).filter(Notification.user_id == user_id).order_by(Notification.created_at.desc()).limit(20).all()
    teams = db.query(Team).join(TeamMember, TeamMember.team_id == Team.id).filter(TeamMember.user_id == user_id).all()
    return templates.TemplateResponse("profile.html", {"request": request, "user": user, "viewer": viewer, "notes": notes, "teams": teams})


@app.post("/admin/role")
def assign_role(request: Request, target_user_id: int = Form(...), role: str = Form(...), db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(404)
    target.role = UserRole(role)
    add_notification(db, target.id, f"Admin {admin.email} assigned you role: {role}")
    db.commit()
    return RedirectResponse(f"/profile/{target.id}", status_code=303)


@app.get("/bootstrap-admin")
def bootstrap_admin(request: Request, db: Session = Depends(get_db)):
    user = require_auth(request, db)
    if db.query(func.count(User.id)).filter(User.role == UserRole.admin).scalar() == 0:
        user.role = UserRole.admin
        db.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/tournaments/new", response_class=HTMLResponse)
def new_tournament_form(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    return templates.TemplateResponse("new_tournament.html", {"request": request})


@app.post("/tournaments")
def create_tournament(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    rules: str = Form(""),
    start_at: str = Form(...),
    registration_open_at: str = Form(...),
    registration_close_at: str = Form(...),
    max_teams: int | None = Form(None),
    team_member_limit: int = Form(6),
    round_title: str = Form(...),
    round_description: str = Form(...),
    tech_requirements: str = Form(...),
    must_have_csv: str = Form(...),
    round_starts_at: str = Form(...),
    round_deadline_at: str = Form(...),
    extra_materials: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    tournament = Tournament(
        title=title,
        description=description,
        rules=rules,
        start_at=datetime.fromisoformat(start_at),
        registration_open_at=datetime.fromisoformat(registration_open_at),
        registration_close_at=datetime.fromisoformat(registration_close_at),
        max_teams=max_teams,
        team_member_limit=team_member_limit,
        status=TournamentStatus.registration,
        created_by_id=admin.id,
    )
    db.add(tournament)
    db.flush()
    db.add(
        Round(
            tournament_id=tournament.id,
            title=round_title,
            description=round_description,
            tech_requirements=tech_requirements,
            must_have_csv=must_have_csv,
            starts_at=datetime.fromisoformat(round_starts_at),
            deadline_at=datetime.fromisoformat(round_deadline_at),
            extra_materials=extra_materials or None,
            status=RoundStatus.draft,
        )
    )
    db.commit()
    return RedirectResponse(url=f"/tournaments/{tournament.id}", status_code=303)


@app.get("/tournaments/{tournament_id}", response_class=HTMLResponse)
def tournament_page(tournament_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        raise HTTPException(404)
    rounds = db.query(Round).filter(Round.tournament_id == tournament_id).order_by(Round.starts_at).all()
    active_round = rounds[-1] if rounds else None
    events = db.query(ScheduleEvent).filter(ScheduleEvent.tournament_id == tournament_id).order_by(ScheduleEvent.starts_at).all()
    anns = db.query(Announcement).filter((Announcement.tournament_id == None) | (Announcement.tournament_id == tournament_id)).order_by(Announcement.created_at.desc()).all()
    leaderboard = build_leaderboard(db, tournament_id)
    return templates.TemplateResponse("tournament.html", {"request": request, "tournament": tournament, "rounds": rounds, "active_round": active_round, "leaderboard": leaderboard, "user": user, "events": events, "announcements": anns})


@app.post("/tournaments/{tournament_id}/register-team")
def register_team(
    tournament_id: int,
    request: Request,
    team_name: str = Form(...),
    member_emails_csv: str = Form(...),
    member_names_csv: str = Form(""),
    city_or_org: str = Form(""),
    contact_handle: str = Form(""),
    db: Session = Depends(get_db),
):
    captain = require_auth(request, db)
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        raise HTTPException(404)
    if not (tournament.registration_open_at <= now() <= tournament.registration_close_at):
        raise HTTPException(400, "Registration window is closed")

    existing = db.query(Team).filter(Team.tournament_id == tournament_id, Team.captain_id == captain.id).first()
    if existing:
        raise HTTPException(400, "Captain already has team in tournament")

    member_emails = parse_csv(member_emails_csv)
    member_names = parse_csv(member_names_csv)
    if len(member_names) not in (0, len(member_emails)):
        raise HTTPException(400, "Member names count must be zero or match emails")
    if len(member_emails) < 1:
        raise HTTPException(400, "At least one member required")
    if len(member_emails) + 1 > tournament.team_member_limit:
        raise HTTPException(400, "Team member limit exceeded")

    if tournament.max_teams:
        if (db.query(func.count(Team.id)).filter(Team.tournament_id == tournament_id).scalar() or 0) >= tournament.max_teams:
            raise HTTPException(400, "Team limit reached")

    team = Team(tournament_id=tournament_id, team_name=team_name, captain_id=captain.id, city_or_org=city_or_org or None, contact_handle=contact_handle or None)
    db.add(team)
    db.flush()
    db.add(TeamMember(team_id=team.id, user_id=captain.id, is_captain=True))
    captain.role = UserRole.participant

    for idx, email in enumerate(member_emails):
        user = db.query(User).filter(User.email == email).first()
        if not user:
            if len(member_names) == 0 or not member_names[idx]:
                raise HTTPException(400, f"Name required for new member: {email}")
            user = User(email=email, password_hash=hash_password("temporary123"), full_name=member_names[idx], profile_completed=False, role=UserRole.participant)
            db.add(user)
            db.flush()
            add_notification(db, user.id, f"You were auto-registered as team member in {tournament.title}. Login and complete profile.")
        user.role = UserRole.participant
        db.add(TeamMember(team_id=team.id, user_id=user.id, is_captain=False))
        add_notification(db, user.id, f"You were added to team {team.team_name} by captain {captain.email}")

    db.commit()
    return RedirectResponse(f"/tournaments/{tournament_id}", status_code=303)


@app.post("/rounds/{round_id}/activate")
def activate_round(round_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    round_ = db.query(Round).filter(Round.id == round_id).first()
    if not round_:
        raise HTTPException(404)
    round_.status = RoundStatus.active
    round_.tournament.status = TournamentStatus.running
    for tm in round_.tournament.teams:
        for m in tm.members:
            add_notification(db, m.user_id, f"Round '{round_.title}' is active")
    db.commit()
    return RedirectResponse(f"/tournaments/{round_.tournament_id}", status_code=303)


@app.post("/rounds/{round_id}/submit")
def upsert_submission(
    round_id: int,
    request: Request,
    team_id: int = Form(...),
    github_url: str = Form(...),
    video_url: str = Form(...),
    live_demo_url: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_auth(request, db)
    member = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == user.id).first()
    if not member:
        raise HTTPException(403, "Not your team")
    round_ = db.query(Round).filter(Round.id == round_id).first()
    if not round_:
        raise HTTPException(404)
    if now() > round_.deadline_at:
        round_.status = RoundStatus.submission_closed
        db.commit()
        raise HTTPException(400, "Submission deadline passed")

    submission = db.query(Submission).filter(Submission.round_id == round_id, Submission.team_id == team_id).first()
    if not submission:
        submission = Submission(round_id=round_id, team_id=team_id, github_url=github_url, video_url=video_url)
        db.add(submission)
    submission.github_url = github_url
    submission.video_url = video_url
    submission.live_demo_url = live_demo_url or None
    submission.description = description or None
    db.commit()
    return RedirectResponse(url=f"/tournaments/{round_.tournament_id}", status_code=303)


@app.post("/rounds/{round_id}/assign-evaluations")
def assign_evaluations(round_id: int, request: Request, min_juries_per_work: int = Form(2), db: Session = Depends(get_db)):
    require_admin(request, db)
    submissions = db.query(Submission).filter(Submission.round_id == round_id).all()
    juries = db.query(User).filter(User.role == UserRole.jury).all()
    if not submissions or not juries:
        raise HTTPException(400, "Need submissions and juries")
    random.shuffle(juries)
    for sub in submissions:
        picks = juries[: min(min_juries_per_work, len(juries))]
        for jury in picks:
            exists = db.query(EvaluationAssignment).filter(EvaluationAssignment.jury_id == jury.id, EvaluationAssignment.submission_id == sub.id).first()
            if not exists:
                db.add(EvaluationAssignment(jury_id=jury.id, submission_id=sub.id))
                add_notification(db, jury.id, f"New work assigned: submission #{sub.id}")
        random.shuffle(juries)
    db.commit()
    return RedirectResponse(f"/tournaments/{submissions[0].round.tournament_id}", status_code=303)


@app.get("/jury", response_class=HTMLResponse)
def jury_page(request: Request, db: Session = Depends(get_db)):
    jury = require_auth(request, db)
    if jury.role != UserRole.jury:
        raise HTTPException(403)
    assignments = db.query(EvaluationAssignment).filter(EvaluationAssignment.jury_id == jury.id).all()
    submission_ids = [a.submission_id for a in assignments]
    submissions = db.query(Submission).filter(Submission.id.in_(submission_ids)).all() if submission_ids else []
    return templates.TemplateResponse("jury.html", {"request": request, "jury": jury, "submissions": submissions})


@app.post("/jury/evaluate/{submission_id}")
def evaluate_submission(
    submission_id: int,
    request: Request,
    backend_score: float = Form(...),
    database_score: float = Form(...),
    frontend_score: float = Form(...),
    functional_score: float = Form(...),
    ux_score: float = Form(...),
    comment: str = Form(""),
    db: Session = Depends(get_db),
):
    jury = require_auth(request, db)
    if jury.role != UserRole.jury:
        raise HTTPException(403)
    evaluation = db.query(Evaluation).filter(Evaluation.jury_id == jury.id, Evaluation.submission_id == submission_id).first()
    if not evaluation:
        evaluation = Evaluation(jury_id=jury.id, submission_id=submission_id, backend_score=0, database_score=0, frontend_score=0, functional_score=0, ux_score=0)
        db.add(evaluation)
    evaluation.backend_score = backend_score
    evaluation.database_score = database_score
    evaluation.frontend_score = frontend_score
    evaluation.functional_score = functional_score
    evaluation.ux_score = ux_score
    evaluation.comment = comment or None
    db.commit()
    return RedirectResponse("/jury", status_code=303)


@app.post("/rounds/{round_id}/finish")
def finish_round(round_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    round_ = db.query(Round).filter(Round.id == round_id).first()
    if not round_:
        raise HTTPException(404)
    round_.status = RoundStatus.evaluated
    round_.tournament.status = TournamentStatus.finished
    db.commit()
    return RedirectResponse(f"/tournaments/{round_.tournament_id}", status_code=303)


@app.get("/leaderboard/{tournament_id}")
def leaderboard_api(tournament_id: int, db: Session = Depends(get_db)):
    return build_leaderboard(db, tournament_id)


@app.get("/leaderboard/{tournament_id}/stream")
def leaderboard_stream(tournament_id: int, db: Session = Depends(get_db)):
    return {"live": True, "data": build_leaderboard(db, tournament_id)}


@app.get("/tournaments/{tournament_id}/export.csv")
def export_csv(tournament_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    data = build_leaderboard(db, tournament_id)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["team_id", "team_name", "score", "evaluations_count"])
    writer.writeheader()
    writer.writerows(data)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=leaderboard.csv"})


@app.get("/certificates/{tournament_id}/{team_id}")
def certificate(tournament_id: int, team_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    team = db.query(Team).filter(Team.id == team_id, Team.tournament_id == tournament_id).first()
    if not team:
        raise HTTPException(404)
    content = f"CERTIFICATE\nTeam: {team.team_name}\nTournament ID: {tournament_id}\nIssued at: {now().isoformat()}\n"
    return StreamingResponse(iter([content]), media_type="text/plain", headers={"Content-Disposition": f"attachment; filename=certificate_team_{team_id}.txt"})


@app.post("/tournaments/{tournament_id}/events")
def create_event(tournament_id: int, request: Request, title: str = Form(...), starts_at: str = Form(...), description: str = Form(""), db: Session = Depends(get_db)):
    require_admin(request, db)
    db.add(ScheduleEvent(tournament_id=tournament_id, title=title, starts_at=datetime.fromisoformat(starts_at), description=description or None))
    db.commit()
    return RedirectResponse(f"/tournaments/{tournament_id}", status_code=303)


@app.post("/announcements")
def create_announcement(request: Request, title: str = Form(...), body: str = Form(...), tournament_id: int | None = Form(None), db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    db.add(Announcement(title=title, body=body, tournament_id=tournament_id, created_by_id=admin.id))
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/archive", response_class=HTMLResponse)
def archive_page(request: Request, db: Session = Depends(get_db)):
    items = db.query(Tournament).filter(Tournament.status == TournamentStatus.finished).order_by(Tournament.start_at.desc()).all()
    return templates.TemplateResponse("archive.html", {"request": request, "items": items})


def build_leaderboard(db: Session, tournament_id: int):
    rounds = db.query(Round).filter(Round.tournament_id == tournament_id).all()
    ids = [r.id for r in rounds]
    submissions = db.query(Submission).filter(Submission.round_id.in_(ids)).all() if ids else []
    by_team: dict[int, list[float]] = defaultdict(list)
    names: dict[int, str] = {}
    for sub in submissions:
        names[sub.team_id] = sub.team.team_name
        for e in sub.evaluations:
            avg = (e.backend_score + e.database_score + e.frontend_score + e.functional_score + e.ux_score) / 5.0
            by_team[sub.team_id].append(avg)
    rows = [{"team_id": tid, "team_name": names[tid], "score": round(sum(vals) / len(vals), 2), "evaluations_count": len(vals)} for tid, vals in by_team.items()]
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows
