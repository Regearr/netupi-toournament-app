from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, Enum):
    admin = "admin"
    team = "team"
    jury = "jury"
    organizer = "organizer"


class TournamentStatus(str, Enum):
    draft = "draft"
    registration = "registration"
    running = "running"
    finished = "finished"


class RoundStatus(str, Enum):
    draft = "draft"
    active = "active"
    submission_closed = "submission_closed"
    evaluated = "evaluated"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), index=True)


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(150), unique=True)
    description: Mapped[str] = mapped_column(Text)
    rules: Mapped[str] = mapped_column(Text, default="")
    start_at: Mapped[datetime] = mapped_column(DateTime)
    registration_open_at: Mapped[datetime] = mapped_column(DateTime)
    registration_close_at: Mapped[datetime] = mapped_column(DateTime)
    max_teams: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team_member_limit: Mapped[int] = mapped_column(Integer, default=6)
    status: Mapped[TournamentStatus] = mapped_column(SAEnum(TournamentStatus), default=TournamentStatus.draft)

    rounds = relationship("Round", back_populates="tournament", cascade="all, delete-orphan")
    teams = relationship("TeamRegistration", back_populates="tournament", cascade="all, delete-orphan")


class TeamRegistration(Base):
    __tablename__ = "team_registrations"
    __table_args__ = (UniqueConstraint("tournament_id", "captain_email", name="uniq_tournament_captain"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), index=True)
    team_name: Mapped[str] = mapped_column(String(150))
    captain_name: Mapped[str] = mapped_column(String(150))
    captain_email: Mapped[str] = mapped_column(String(150))
    member_emails_csv: Mapped[str] = mapped_column(Text)
    member_names_csv: Mapped[str] = mapped_column(Text)
    city_or_org: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contact_handle: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tournament = relationship("Tournament", back_populates="teams")
    submissions = relationship("Submission", back_populates="team", cascade="all, delete-orphan")


class Round(Base):
    __tablename__ = "rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), index=True)
    title: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text)
    tech_requirements: Mapped[str] = mapped_column(Text)
    must_have_csv: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    deadline_at: Mapped[datetime] = mapped_column(DateTime)
    extra_materials: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RoundStatus] = mapped_column(SAEnum(RoundStatus), default=RoundStatus.draft)

    tournament = relationship("Tournament", back_populates="rounds")
    submissions = relationship("Submission", back_populates="round", cascade="all, delete-orphan")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("team_id", "round_id", name="uniq_team_round_submission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team_registrations.id"), index=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), index=True)
    github_url: Mapped[str] = mapped_column(String(300))
    video_url: Mapped[str] = mapped_column(String(300))
    live_demo_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    team = relationship("TeamRegistration", back_populates="submissions")
    round = relationship("Round", back_populates="submissions")
    evaluations = relationship("Evaluation", back_populates="submission", cascade="all, delete-orphan")


class EvaluationAssignment(Base):
    __tablename__ = "evaluation_assignments"
    __table_args__ = (UniqueConstraint("jury_id", "submission_id", name="uniq_jury_submission_assignment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jury_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (UniqueConstraint("jury_id", "submission_id", name="uniq_jury_submission_evaluation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jury_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)

    backend_score: Mapped[float] = mapped_column(Float)
    database_score: Mapped[float] = mapped_column(Float)
    frontend_score: Mapped[float] = mapped_column(Float)
    functional_score: Mapped[float] = mapped_column(Float)
    ux_score: Mapped[float] = mapped_column(Float)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    submission = relationship("Submission", back_populates="evaluations")
