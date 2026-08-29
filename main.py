"""
Mission Control - backend API.
Phase 1: teams, membership, features, checkpoints, comments.
"""

from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from sqlmodel import Session, select
from pydantic import BaseModel

from database import create_db_and_tables, get_session
from models import User, Team, Membership, Feature, Checkpoint, Milestone, Comment, Role, RunStatus

app = FastAPI(title="Mission Control API")


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


# ---------- Request/response schemas (not DB tables, just API shapes) ----------

class CreateUserRequest(BaseModel):
    name: str
    email: str


class CreateTeamRequest(BaseModel):
    name: str
    lead_user_id: int


class JoinTeamRequest(BaseModel):
    invite_code: str
    user_id: int


class CreateFeatureRequest(BaseModel):
    team_id: int
    owner_id: int
    name: str
    description: Optional[str] = None


# ---------- Response schemas (plain Pydantic, not table models) ----------
# We deliberately don't use the SQLModel table classes (User, Team, ...) as
# response_model directly - their relationship fields cause FastAPI/Pydantic
# to serialize them as empty objects. These mirror only the fields we want
# to expose over the API.

class UserRead(BaseModel):
    id: int
    name: str
    email: str
    created_at: datetime


class TeamRead(BaseModel):
    id: int
    name: str
    invite_code: str
    created_at: datetime
    checkpoint_retention: str


class FeatureRead(BaseModel):
    id: int
    team_id: int
    owner_id: int
    name: str
    description: Optional[str]
    created_at: datetime
    is_done: bool
    is_approved: bool


class CheckpointCreate(BaseModel):
    feature_id: int
    diff_content: str
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    run_status: RunStatus = RunStatus.unknown
    run_output: Optional[str] = None


class CheckpointRead(BaseModel):
    id: int
    feature_id: int
    diff_content: str
    files_changed: int
    lines_added: int
    lines_removed: int
    run_status: RunStatus
    run_output: Optional[str]
    created_at: datetime


class CommentCreate(BaseModel):
    checkpoint_id: int
    author_id: int
    body: str


class CommentRead(BaseModel):
    id: int
    checkpoint_id: int
    author_id: int
    author_name: str
    body: str
    created_at: datetime


# ---------- Users ----------

@app.post("/users", response_model=UserRead)
def create_user(req: CreateUserRequest, session: Session = Depends(get_session)):
    existing = session.exec(select(User).where(User.email == req.email)).first()
    if existing:
        raise HTTPException(400, "A user with this email already exists")
    user = User(name=req.name, email=req.email)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# ---------- Teams ----------

@app.post("/teams", response_model=TeamRead)
def create_team(req: CreateTeamRequest, session: Session = Depends(get_session)):
    lead = session.get(User, req.lead_user_id)
    if not lead:
        raise HTTPException(404, "Lead user not found")

    team = Team(name=req.name)
    session.add(team)
    session.commit()
    session.refresh(team)

    membership = Membership(user_id=lead.id, team_id=team.id, role=Role.lead)
    session.add(membership)
    session.commit()

    return team


@app.post("/teams/join")
def join_team(req: JoinTeamRequest, session: Session = Depends(get_session)):
    team = session.exec(select(Team).where(Team.invite_code == req.invite_code)).first()
    if not team:
        raise HTTPException(404, "Invalid invite code")

    user = session.get(User, req.user_id)
    if not user:
        raise HTTPException(404, "User not found")

    existing = session.exec(
        select(Membership).where(Membership.team_id == team.id, Membership.user_id == user.id)
    ).first()
    if existing:
        raise HTTPException(400, "Already a member of this team")

    membership = Membership(user_id=user.id, team_id=team.id, role=Role.member)
    session.add(membership)
    session.commit()

    return {"team_id": team.id, "team_name": team.name, "role": "member"}


@app.get("/teams/{team_id}/members")
def list_team_members(team_id: int, session: Session = Depends(get_session)):
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")

    memberships = session.exec(select(Membership).where(Membership.team_id == team_id)).all()
    result = []
    for m in memberships:
        user = session.get(User, m.user_id)
        result.append({"user_id": user.id, "name": user.name, "role": m.role})
    return result


# ---------- Features ----------

@app.post("/features", response_model=FeatureRead)
def claim_feature(req: CreateFeatureRequest, session: Session = Depends(get_session)):
    membership = session.exec(
        select(Membership).where(Membership.team_id == req.team_id, Membership.user_id == req.owner_id)
    ).first()
    if not membership:
        raise HTTPException(403, "User is not a member of this team")

    feature = Feature(
        team_id=req.team_id,
        owner_id=req.owner_id,
        name=req.name,
        description=req.description,
    )
    session.add(feature)
    session.commit()
    session.refresh(feature)
    return feature


@app.get("/teams/{team_id}/dashboard")
def get_dashboard(team_id: int, session: Session = Depends(get_session)):
    """The main tile-grid view: every feature in the team, plus its most recent checkpoint."""
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")

    features = session.exec(select(Feature).where(Feature.team_id == team_id)).all()

    tiles = []
    for f in features:
        owner = session.get(User, f.owner_id)
        latest_checkpoint = session.exec(
            select(Checkpoint)
            .where(Checkpoint.feature_id == f.id)
            .order_by(Checkpoint.created_at.desc())
        ).first()

        tiles.append({
            "feature_id": f.id,
            "feature_name": f.name,
            "owner_name": owner.name if owner else "Unknown",
            "is_done": f.is_done,
            "is_approved": f.is_approved,
            "latest_checkpoint": {
                "created_at": latest_checkpoint.created_at,
                "run_status": latest_checkpoint.run_status,
                "files_changed": latest_checkpoint.files_changed,
                "lines_added": latest_checkpoint.lines_added,
                "lines_removed": latest_checkpoint.lines_removed,
            } if latest_checkpoint else None,
        })

    return {"team_id": team_id, "team_name": team.name, "tiles": tiles}


# ---------- Checkpoints ----------

@app.post("/checkpoints", response_model=CheckpointRead)
def create_checkpoint(req: CheckpointCreate, session: Session = Depends(get_session)):
    """Called by the watcher script on each save/commit. Stores a new checkpoint
    and enforces the team's retention policy (keep 'all' or last N per feature)."""
    feature = session.get(Feature, req.feature_id)
    if not feature:
        raise HTTPException(404, "Feature not found")

    checkpoint = Checkpoint(
        feature_id=req.feature_id,
        diff_content=req.diff_content,
        files_changed=req.files_changed,
        lines_added=req.lines_added,
        lines_removed=req.lines_removed,
        run_status=req.run_status,
        run_output=req.run_output,
    )
    session.add(checkpoint)
    session.commit()
    session.refresh(checkpoint)

    # Enforce retention: if the team caps checkpoint count, delete the oldest
    # ones beyond that cap for this feature. "all" means never prune.
    team = session.get(Team, feature.team_id)
    if team and team.checkpoint_retention != "all":
        try:
            keep_n = int(team.checkpoint_retention)
        except ValueError:
            keep_n = None  # malformed value - fail safe by not pruning

        if keep_n is not None:
            all_checkpoints = session.exec(
                select(Checkpoint)
                .where(Checkpoint.feature_id == req.feature_id)
                .order_by(Checkpoint.created_at.desc())
            ).all()
            for old in all_checkpoints[keep_n:]:
                session.delete(old)
            session.commit()

    return checkpoint


@app.get("/features/{feature_id}/checkpoints", response_model=list[CheckpointRead])
def list_checkpoints(feature_id: int, session: Session = Depends(get_session)):
    """Full checkpoint history for a feature (newest first) - the timeline view
    you see after clicking into a tile."""
    feature = session.get(Feature, feature_id)
    if not feature:
        raise HTTPException(404, "Feature not found")

    checkpoints = session.exec(
        select(Checkpoint)
        .where(Checkpoint.feature_id == feature_id)
        .order_by(Checkpoint.created_at.desc())
    ).all()
    return checkpoints


# ---------- Comments ----------

@app.post("/comments", response_model=CommentRead)
def create_comment(req: CommentCreate, session: Session = Depends(get_session)):
    """Lead (or anyone on the team) leaves a note anchored to a specific checkpoint."""
    checkpoint = session.get(Checkpoint, req.checkpoint_id)
    if not checkpoint:
        raise HTTPException(404, "Checkpoint not found")

    author = session.get(User, req.author_id)
    if not author:
        raise HTTPException(404, "Author not found")

    comment = Comment(checkpoint_id=req.checkpoint_id, author_id=req.author_id, body=req.body)
    session.add(comment)
    session.commit()
    session.refresh(comment)

    return CommentRead(
        id=comment.id,
        checkpoint_id=comment.checkpoint_id,
        author_id=comment.author_id,
        author_name=author.name,
        body=comment.body,
        created_at=comment.created_at,
    )


@app.get("/checkpoints/{checkpoint_id}/comments", response_model=list[CommentRead])
def list_comments(checkpoint_id: int, session: Session = Depends(get_session)):
    checkpoint = session.get(Checkpoint, checkpoint_id)
    if not checkpoint:
        raise HTTPException(404, "Checkpoint not found")

    comments = session.exec(
        select(Comment).where(Comment.checkpoint_id == checkpoint_id).order_by(Comment.created_at)
    ).all()

    result = []
    for c in comments:
        author = session.get(User, c.author_id)
        result.append(CommentRead(
            id=c.id,
            checkpoint_id=c.checkpoint_id,
            author_id=c.author_id,
            author_name=author.name if author else "Unknown",
            body=c.body,
            created_at=c.created_at,
        ))
    return result
