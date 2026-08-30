"""
Mission Control - backend API.
Phase 1+2: teams, membership, features, checkpoints, comments - now with
real authentication (email/password + JWT) and authorization (every
endpoint verifies the requester is actually allowed to see/do what they're
asking for, instead of trusting a raw user_id in the request body).
"""

from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel import Session, select
from pydantic import BaseModel, EmailStr, Field, field_validator

from database import create_db_and_tables, get_session
from models import User, Team, Membership, Feature, Checkpoint, Milestone, Comment, Role, RunStatus
from auth import hash_password, verify_password, create_access_token, decode_access_token

app = FastAPI(title="Mission Control API")

bearer_scheme = HTTPBearer()


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


# ---------- Auth dependency ----------
# Every protected endpoint takes current_user: User = Depends(get_current_user)
# instead of trusting a user_id the caller typed into the request body.

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    session: Session = Depends(get_session), ) -> User:
    token = credentials.credentials
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(401, "Invalid or expired token")

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(401, "User no longer exists")
    return user


def require_team_membership(team_id: int, user: User, session: Session) -> Membership:
    """Raises 403 if the user isn't a member of this team. Returns the
    membership row (so callers can check .role for lead-only actions)."""
    membership = session.exec(
        select(Membership).where(Membership.team_id == team_id, Membership.user_id == user.id)
    ).first()
    if not membership:
        raise HTTPException(403, "You are not a member of this team")
    return membership


# ---------- Request/response schemas ----------

class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # 72 = bcrypt's hard byte limit

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        # Field(min_length=1) still allows "   " (whitespace-only) to pass,
        # so we strip and re-check here.
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be blank")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if v.isdigit():
            raise ValueError("Password cannot be all numbers")
        if v.lower() in ("password", "12345678", "password123", "qwertyui"):
            raise ValueError("This password is too common - please choose another")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)  # login just needs "was something submitted"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    name: str


class CreateTeamRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Team name cannot be blank")
        return v


class JoinTeamRequest(BaseModel):
    invite_code: str = Field(min_length=1, max_length=32)


class CreateFeatureRequest(BaseModel):
    team_id: int
    name: str = Field(min_length=1, max_length=150)
    description: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Feature name cannot be blank")
        return v


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
    diff_content: str = Field(max_length=500_000)  # generous but bounded - stops a runaway diff from blowing up storage
    files_changed: int = Field(default=0, ge=0)
    lines_added: int = Field(default=0, ge=0)
    lines_removed: int = Field(default=0, ge=0)
    run_status: RunStatus = RunStatus.unknown
    run_output: Optional[str] = Field(default=None, max_length=5000)


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
    body: str = Field(min_length=1, max_length=3000)

    @field_validator("body")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Comment cannot be blank")
        return v


class CommentRead(BaseModel):
    id: int
    checkpoint_id: int
    author_id: int
    author_name: str
    body: str
    created_at: datetime


# ---------- Auth endpoints ----------

@app.post("/auth/signup", response_model=TokenResponse)
def signup(req: SignupRequest, session: Session = Depends(get_session)):
    existing = session.exec(select(User).where(User.email == req.email)).first()
    if existing:
        raise HTTPException(400, "A user with this email already exists")

    user = User(name=req.name, email=req.email, password_hash=hash_password(req.password))
    session.add(user)
    session.commit()
    session.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user_id=user.id, name=user.name)


@app.post("/auth/login", response_model=TokenResponse)
def login(req: LoginRequest, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == req.email)).first()
    # Deliberately same error for "no such user" and "wrong password" - telling
    # an attacker which one it was would let them enumerate valid emails.
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user_id=user.id, name=user.name)


@app.get("/auth/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# ---------- Teams ----------

@app.post("/teams", response_model=TeamRead)
def create_team(
    req: CreateTeamRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team = Team(name=req.name)
    session.add(team)
    session.commit()
    session.refresh(team)

    membership = Membership(user_id=current_user.id, team_id=team.id, role=Role.lead)
    session.add(membership)
    session.commit()

    return team


@app.post("/teams/join")
def join_team(
    req: JoinTeamRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team = session.exec(select(Team).where(Team.invite_code == req.invite_code)).first()
    if not team:
        raise HTTPException(404, "Invalid invite code")

    existing = session.exec(
        select(Membership).where(Membership.team_id == team.id, Membership.user_id == current_user.id)
    ).first()
    if existing:
        raise HTTPException(400, "Already a member of this team")

    membership = Membership(user_id=current_user.id, team_id=team.id, role=Role.member)
    session.add(membership)
    session.commit()

    return {"team_id": team.id, "team_name": team.name, "role": "member"}


@app.get("/teams/{team_id}/members")
def list_team_members(
    team_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_team_membership(team_id, current_user, session)

    memberships = session.exec(select(Membership).where(Membership.team_id == team_id)).all()
    result = []
    for m in memberships:
        user = session.get(User, m.user_id)
        result.append({"user_id": user.id, "name": user.name, "role": m.role})
    return result


# ---------- Features ----------

@app.post("/features", response_model=FeatureRead)
def claim_feature(
    req: CreateFeatureRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_team_membership(req.team_id, current_user, session)

    feature = Feature(
        team_id=req.team_id,
        owner_id=current_user.id,
        name=req.name,
        description=req.description,
    )
    session.add(feature)
    session.commit()
    session.refresh(feature)
    return feature


@app.get("/teams/{team_id}/dashboard")
def get_dashboard(
    team_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """The main tile-grid view. Requires team membership - this is the endpoint
    that would leak everyone's code if left unprotected."""
    require_team_membership(team_id, current_user, session)

    team = session.get(Team, team_id)
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
def create_checkpoint(
    req: CheckpointCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Called by the watcher script (which now needs an access token - see
    watcher.py's --token argument) on each save. Stores a checkpoint and
    enforces the team's retention policy."""
    feature = session.get(Feature, req.feature_id)
    if not feature:
        raise HTTPException(404, "Feature not found")

    if feature.owner_id != current_user.id:
        raise HTTPException(403, "You can only post checkpoints for your own features")

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

    team = session.get(Team, feature.team_id)
    if team and team.checkpoint_retention != "all":
        try:
            keep_n = int(team.checkpoint_retention)
        except ValueError:
            keep_n = None

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
def list_checkpoints(
    feature_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    feature = session.get(Feature, feature_id)
    if not feature:
        raise HTTPException(404, "Feature not found")

    require_team_membership(feature.team_id, current_user, session)

    checkpoints = session.exec(
        select(Checkpoint)
        .where(Checkpoint.feature_id == feature_id)
        .order_by(Checkpoint.created_at.desc())
    ).all()
    return checkpoints


# ---------- Comments ----------

@app.post("/comments", response_model=CommentRead)
def create_comment(
    req: CommentCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    checkpoint = session.get(Checkpoint, req.checkpoint_id)
    if not checkpoint:
        raise HTTPException(404, "Checkpoint not found")

    feature = session.get(Feature, checkpoint.feature_id)
    require_team_membership(feature.team_id, current_user, session)

    comment = Comment(checkpoint_id=req.checkpoint_id, author_id=current_user.id, body=req.body)
    session.add(comment)
    session.commit()
    session.refresh(comment)

    return CommentRead(
        id=comment.id,
        checkpoint_id=comment.checkpoint_id,
        author_id=comment.author_id,
        author_name=current_user.name,
        body=comment.body,
        created_at=comment.created_at,
    )


@app.get("/checkpoints/{checkpoint_id}/comments", response_model=list[CommentRead])
def list_comments(
    checkpoint_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    checkpoint = session.get(Checkpoint, checkpoint_id)
    if not checkpoint:
        raise HTTPException(404, "Checkpoint not found")

    feature = session.get(Feature, checkpoint.feature_id)
    require_team_membership(feature.team_id, current_user, session)

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
