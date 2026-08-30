"""
Database schema for the team mission-control dashboard.
Built with SQLModel (FastAPI-native ORM + Pydantic validation in one).
"""

from datetime import datetime
from typing import Optional
from enum import Enum
import uuid

from sqlmodel import SQLModel, Field, Relationship


# ---------- Enums ----------

class Role(str, Enum):
    lead = "lead"
    member = "member"


class RunStatus(str, Enum):
    unknown = "unknown"      # no run reported yet
    running_clean = "clean"  # exit code 0
    crashing = "crashing"    # non-zero exit code
    checking = "checking"    # run in progress


# ---------- Core tables ----------

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(unique=True, index=True)
    password_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    memberships: list["Membership"] = Relationship(back_populates="user")


class Team(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    invite_code: str = Field(
        default_factory=lambda: uuid.uuid4().hex[:8], unique=True, index=True
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Retention policy for checkpoints: "all" = keep forever, or an integer N
    # (stored as string so "all" and numbers share one column; parse on use)
    # v1 behavior: pruning hard-deletes the whole checkpoint row (diff + metadata).
    # TODO (later): option to keep timestamp/run_status and only drop diff_content,
    # so activity history survives even after the diff itself is pruned.
    checkpoint_retention: str = Field(default="all")

    memberships: list["Membership"] = Relationship(back_populates="team")
    features: list["Feature"] = Relationship(back_populates="team")
    milestones: list["Milestone"] = Relationship(back_populates="team")


class Membership(SQLModel, table=True):
    """Links a User to a Team with a role. A user can be lead of one team
    and a plain member of another, so role lives here, not on User."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    team_id: int = Field(foreign_key="team.id")
    role: Role = Field(default=Role.member)
    joined_at: datetime = Field(default_factory=datetime.utcnow)

    user: User = Relationship(back_populates="memberships")
    team: Team = Relationship(back_populates="memberships")


class Feature(SQLModel, table=True):
    """What a member has claimed to work on. This is what a 'tile' represents."""
    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id")
    owner_id: int = Field(foreign_key="user.id")  # which member owns this tile
    name: str  # e.g. "Login page", "Payment integration"
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_done: bool = Field(default=False)  # member marked ready for review
    is_approved: bool = Field(default=False)  # lead approved it

    team: Team = Relationship(back_populates="features")
    checkpoints: list["Checkpoint"] = Relationship(back_populates="feature")


class Checkpoint(SQLModel, table=True):
    """A snapshot of a feature's code state at a point in time.
    Created by the watcher script on save/commit, or a manual button press."""
    id: Optional[int] = Field(default=None, primary_key=True)
    feature_id: int = Field(foreign_key="feature.id")
    diff_content: str  # unified diff text since last checkpoint
    files_changed: int = Field(default=0)
    lines_added: int = Field(default=0)
    lines_removed: int = Field(default=0)
    run_status: RunStatus = Field(default=RunStatus.unknown)
    run_output: Optional[str] = None  # stdout/stderr tail, for error context
    created_at: datetime = Field(default_factory=datetime.utcnow)

    feature: Feature = Relationship(back_populates="checkpoints")
    comments: list["Comment"] = Relationship(back_populates="checkpoint")


class Milestone(SQLModel, table=True):
    """A lead-blessed, whole-project snapshot at a known-good working state —
    distinct from a per-feature Checkpoint. Think 'git tag' / release point,
    not a diff-since-last-save. Used for 'save this as our safe rollback point'."""
    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id")
    created_by_id: int = Field(foreign_key="user.id")  # should be the lead
    label: str  # e.g. "Working demo before judging", "Auth + payments stable"
    # Reference to the actual code state — e.g. a git commit SHA/tag if the
    # team's repo is on GitHub, so we don't have to store the full codebase ourselves
    git_ref: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    team: Team = Relationship(back_populates="milestones")


class Comment(SQLModel, table=True):
    """A lead's note, anchored to a specific checkpoint (Figma-comment-on-a-frame style)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    checkpoint_id: int = Field(foreign_key="checkpoint.id")
    author_id: int = Field(foreign_key="user.id")
    body: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    checkpoint: Checkpoint = Relationship(back_populates="comments")
