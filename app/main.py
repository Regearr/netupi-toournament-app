from __future__ import annotations

import random
from collections import defaultdict
from datetime import datetime

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import (
    Evaluation,
    EvaluationAssignment,
    Round,
    RoundStatus,
    Submission,
    TeamRegistration,
    Tournament,
    TournamentStatus,
    User,
    UserRole,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Tournament Platform")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def now() -> datetime:
    return datetime.utcnow()


def parse_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    tournaments = db.query(Tournament).order_by(Tournament.start_at.desc()).all()
    return templates.TemplateResponse("home.html", {"request": request, "tournaments": tournaments})


@app.post("/users/seed")
def seed_users(db: Session = Depends(get_db)):
    users = [
        ("Admin User", "admin@example.com", UserRole.admin),
        ("Organizer User", "organizer@example.com", UserRole.organizer),
        ("Jury One", "jury1@example.com", UserRole.jury),
        ("Jury Two", "jury2@example.com", UserRole.jury),
        ("Jury Three", "jury3@example.com", UserRole.jury),
    ]
    created = 0
    for full_name, email, role in users:
        if not db.query(User).filter(User.email == email).first():
            db.add(User(full_name=full_name, email=email, role=role))
            created += 1
    db.commit()
    return {"created": created}


@app.get("/tournaments/new", response_class=HTMLResponse)
def new_tournament_form(request: Request):
    return templates.TemplateResponse("new_tournament.html", {"request": request})


@app.post("/tournaments")
def create_tournament(
    title: str = Form(...),
    description: str = Form(...),
    rules: str = Form(""),
    start_at: str = Form(...),
    registration_open_at: str = Form(...),
    registration_close_at: str = Form(...),
    max_teams: int | None = Form(None),
    team_member_limit: int = Form(6),
    db: Session = Depends(get_db),
):
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
    )
    db.add(tournament)
    db.commit()
    return RedirectResponse(url=f"/tournaments/{tournament.id}", status_code=303)


@app.get("/tournaments/{tournament_id}", response_class=HTMLResponse)
def tournament_page(tournament_id: int, request: Request, db: Session = Depends(get_db)):
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        raise HTTPException(404)
    active_round = (
        db.query(Round)
        .filter(Round.tournament_id == tournament_id)
        .order_by(Round.starts_at.desc())
        .first()
    )
    leaderboard = build_leaderboard(db, tournament_id)
    return templates.TemplateResponse(
        "tournament.html",
        {
            "request": request,
            "tournament": tournament,
            "active_round": active_round,
            "leaderboard": leaderboard,
            "now": now(),
        },
    )


@app.post("/tournaments/{tournament_id}/register")
def register_team(
    tournament_id: int,
    team_name: str = Form(...),
    captain_name: str = Form(...),
    captain_email: str = Form(...),
    member_names_csv: str = Form(...),
    member_emails_csv: str = Form(...),
    city_or_org: str = Form(""),
    contact_handle: str = Form(""),
    db: Session = Depends(get_db),
):
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        raise HTTPException(404, "Tournament not found")
    if not (tournament.registration_open_at <= now() <= tournament.registration_close_at):
        raise HTTPException(400, "Registration window is closed")
    existing = db.query(TeamRegistration).filter(
        TeamRegistration.tournament_id == tournament_id,
        TeamRegistration.captain_email == captain_email,
    ).first()
    if existing:
        raise HTTPException(400, "Captain already registered in this tournament")

    member_names = parse_csv(member_names_csv)
    member_emails = parse_csv(member_emails_csv)
    if len(member_names) != len(member_emails):
        raise HTTPException(400, "Members names/emails mismatch")
    if len(member_names) < 2 or len(member_names) > tournament.team_member_limit:
        raise HTTPException(400, "Team member count violates limits")
    if len(set(member_emails + [captain_email])) != len(member_emails) + 1:
        raise HTTPException(400, "Duplicate emails in team")

    if tournament.max_teams:
        teams_count = db.query(func.count(TeamRegistration.id)).filter(TeamRegistration.tournament_id == tournament_id).scalar() or 0
        if teams_count >= tournament.max_teams:
            raise HTTPException(400, "Team limit reached")

    team = TeamRegistration(
        tournament_id=tournament_id,
        team_name=team_name,
        captain_name=captain_name,
        captain_email=captain_email,
        member_names_csv=member_names_csv,
        member_emails_csv=member_emails_csv,
        city_or_org=city_or_org or None,
        contact_handle=contact_handle or None,
    )
    db.add(team)
    db.commit()
    return RedirectResponse(url=f"/tournaments/{tournament_id}", status_code=303)


@app.post("/tournaments/{tournament_id}/rounds")
def create_round(
    tournament_id: int,
    title: str = Form(...),
    description: str = Form(...),
    tech_requirements: str = Form(...),
    must_have_csv: str = Form(...),
    starts_at: str = Form(...),
    deadline_at: str = Form(...),
    extra_materials: str = Form(""),
    db: Session = Depends(get_db),
):
    round_ = Round(
        tournament_id=tournament_id,
        title=title,
        description=description,
        tech_requirements=tech_requirements,
        must_have_csv=must_have_csv,
        starts_at=datetime.fromisoformat(starts_at),
        deadline_at=datetime.fromisoformat(deadline_at),
        extra_materials=extra_materials or None,
        status=RoundStatus.active,
    )
    db.add(round_)
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if tournament:
        tournament.status = TournamentStatus.running
    db.commit()
    return RedirectResponse(url=f"/tournaments/{tournament_id}", status_code=303)


@app.post("/rounds/{round_id}/submit")
def upsert_submission(
    round_id: int,
    team_id: int = Form(...),
    github_url: str = Form(...),
    video_url: str = Form(...),
    live_demo_url: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
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
def assign_evaluations(round_id: int, min_juries_per_work: int = Form(2), db: Session = Depends(get_db)):
    round_ = db.query(Round).filter(Round.id == round_id).first()
    if not round_:
        raise HTTPException(404)
    submissions = db.query(Submission).filter(Submission.round_id == round_id).all()
    juries = db.query(User).filter(User.role == UserRole.jury).all()
    if not submissions or not juries:
        raise HTTPException(400, "Need submissions and jury members")

    random.shuffle(juries)
    for submission in submissions:
        picks = juries[: min(min_juries_per_work, len(juries))]
        for jury in picks:
            exists = db.query(EvaluationAssignment).filter(
                EvaluationAssignment.jury_id == jury.id,
                EvaluationAssignment.submission_id == submission.id,
            ).first()
            if not exists:
                db.add(EvaluationAssignment(jury_id=jury.id, submission_id=submission.id))
        random.shuffle(juries)
    db.commit()
    return {"assigned": True}


@app.get("/jury/{jury_id}", response_class=HTMLResponse)
def jury_page(jury_id: int, request: Request, db: Session = Depends(get_db)):
    jury = db.query(User).filter(User.id == jury_id, User.role == UserRole.jury).first()
    if not jury:
        raise HTTPException(404)
    assignments = db.query(EvaluationAssignment).filter(EvaluationAssignment.jury_id == jury_id).all()
    submission_ids = [a.submission_id for a in assignments]
    submissions = db.query(Submission).filter(Submission.id.in_(submission_ids)).all() if submission_ids else []
    return templates.TemplateResponse("jury.html", {"request": request, "jury": jury, "submissions": submissions})


@app.post("/jury/{jury_id}/evaluate/{submission_id}")
def evaluate_submission(
    jury_id: int,
    submission_id: int,
    backend_score: float = Form(...),
    database_score: float = Form(...),
    frontend_score: float = Form(...),
    functional_score: float = Form(...),
    ux_score: float = Form(...),
    comment: str = Form(""),
    db: Session = Depends(get_db),
):
    for s in [backend_score, database_score, frontend_score, functional_score, ux_score]:
        if s < 0 or s > 100:
            raise HTTPException(400, "Scores must be in 0..100")
    evaluation = db.query(Evaluation).filter(Evaluation.jury_id == jury_id, Evaluation.submission_id == submission_id).first()
    if not evaluation:
        evaluation = Evaluation(jury_id=jury_id, submission_id=submission_id, backend_score=backend_score, database_score=database_score, frontend_score=frontend_score, functional_score=functional_score, ux_score=ux_score)
        db.add(evaluation)
    evaluation.backend_score = backend_score
    evaluation.database_score = database_score
    evaluation.frontend_score = frontend_score
    evaluation.functional_score = functional_score
    evaluation.ux_score = ux_score
    evaluation.comment = comment or None
    db.commit()
    return RedirectResponse(url=f"/jury/{jury_id}", status_code=303)


@app.post("/rounds/{round_id}/finish")
def finish_evaluation(round_id: int, db: Session = Depends(get_db)):
    round_ = db.query(Round).filter(Round.id == round_id).first()
    if not round_:
        raise HTTPException(404)
    round_.status = RoundStatus.evaluated
    tournament = db.query(Tournament).filter(Tournament.id == round_.tournament_id).first()
    if tournament:
        tournament.status = TournamentStatus.finished
    db.commit()
    return RedirectResponse(url=f"/tournaments/{round_.tournament_id}", status_code=303)


@app.get("/leaderboard/{tournament_id}")
def leaderboard(tournament_id: int, db: Session = Depends(get_db)):
    return build_leaderboard(db, tournament_id)


@app.get("/profile/{email}")
def profile(email: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(404)
    result: dict = {"user": {"name": user.full_name, "email": user.email, "role": user.role.value}}
    if user.role in {UserRole.admin, UserRole.organizer}:
        result["tournaments"] = [t.title for t in db.query(Tournament).all()]
    if user.role == UserRole.jury:
        evals = db.query(Evaluation).filter(Evaluation.jury_id == user.id).all()
        result["evaluated_submissions"] = [e.submission_id for e in evals]
    return result


def build_leaderboard(db: Session, tournament_id: int):
    rounds = db.query(Round).filter(Round.tournament_id == tournament_id).all()
    round_ids = [r.id for r in rounds]
    submissions = db.query(Submission).filter(Submission.round_id.in_(round_ids)).all() if round_ids else []

    by_team: dict[int, list[float]] = defaultdict(list)
    team_names: dict[int, str] = {}
    for submission in submissions:
        team_names[submission.team_id] = submission.team.team_name
        for e in submission.evaluations:
            total = (e.backend_score + e.database_score + e.frontend_score + e.functional_score + e.ux_score) / 5.0
            by_team[submission.team_id].append(total)

    result = []
    for team_id, values in by_team.items():
        result.append(
            {
                "team_id": team_id,
                "team_name": team_names[team_id],
                "score": round(sum(values) / len(values), 2) if values else 0,
                "evaluations_count": len(values),
            }
        )
    result.sort(key=lambda x: x["score"], reverse=True)
    return result
