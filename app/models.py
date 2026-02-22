from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, Enum):
    visitor = "visitor"
    admin = "admin"
    participant = "participant"
    jury = "jury"


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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    full_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    school_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contact_info: Mapped[str | None] = mapped_column(String(150), nullable=True)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.visitor, index=True)
    profile_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    rounds = relationship("Round", back_populates="tournament", cascade="all, delete-orphan")
    teams = relationship("Team", back_populates="tournament", cascade="all, delete-orphan")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), index=True)
    team_name: Mapped[str] = mapped_column(String(150))
    captain_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    city_or_org: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contact_handle: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tournament = relationship("Tournament", back_populates="teams")
    members = relationship("TeamMember", back_populates="team", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="team", cascade="all, delete-orphan")


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uniq_team_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    is_captain: Mapped[bool] = mapped_column(Boolean, default=False)

    team = relationship("Team", back_populates="members")


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
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), index=True)
    github_url: Mapped[str] = mapped_column(String(300))
    video_url: Mapped[str] = mapped_column(String(300))
    live_demo_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    team = relationship("Team", back_populates="submissions")
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


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    message: Mapped[str] = mapped_column(String(255))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ScheduleEvent(Base):
    __tablename__ = "schedule_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), index=True)
    title: Mapped[str] = mapped_column(String(150))
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int | None] = mapped_column(ForeignKey("tournaments.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(150))
    body: Mapped[str] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
