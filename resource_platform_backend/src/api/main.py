import os
from typing import List, Optional, Dict, Any, Callable, Iterable
from threading import Lock
from uuid import uuid4
from datetime import datetime

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Query, Path, Header, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, EmailStr

# In-memory stores with thread-safety via locks
class ThreadSafeStore:
    """Simple thread-safe in-memory store using dict internally with a lock."""
    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._data.values())

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._data.get(item_id)

    def create(self, item: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            item_id = item.get("id") or str(uuid4())
            item["id"] = item_id
            self._data[item_id] = item
            return item

    def update(self, item_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            if item_id not in self._data:
                raise KeyError(item_id)
            self._data[item_id].update(updates)
            return self._data[item_id]

    def delete(self, item_id: str) -> None:
        with self._lock:
            if item_id not in self._data:
                raise KeyError(item_id)
            del self._data[item_id]


# Global stores
users_store = ThreadSafeStore()
sessions_store = ThreadSafeStore()
projects_store = ThreadSafeStore()
tasks_store = ThreadSafeStore()
resources_store = ThreadSafeStore()
approvals_store = ThreadSafeStore()

# Seed in-memory users with roles for demo
def _seed_users_once():
    if users_store.list():
        return
    now = datetime.utcnow().isoformat() + "Z"
    for user in [
        {"email": "admin@example.com", "name": "Admin User", "password": "admin123", "role": "admin"},
        {"email": "manager@example.com", "name": "Manager User", "password": "manager123", "role": "manager"},
        {"email": "user@example.com", "name": "Standard User", "password": "user123", "role": "user"},
    ]:
        users_store.create({
            "id": str(uuid4()),
            "email": user["email"],
            "name": user["name"],
            "password": user["password"],
            "role": user["role"],
            "created_at": now
        })
_seed_users_once()

# Shared utilities
def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

def _iso_to_date_str(iso_ts: Optional[str]) -> Optional[str]:
    """Convert an ISO timestamp with optional trailing Z into YYYY-MM-DD date string."""
    if not iso_ts:
        return None
    ts = iso_ts.rstrip("Z")
    try:
        # Try parsing fractional seconds as well
        dt = datetime.fromisoformat(ts)
        return dt.date().isoformat()
    except Exception:
        return None


# PUBLIC_INTERFACE
class HealthResponse(BaseModel):
    """Health endpoint response."""
    status: str = Field(..., description="Health status string")
    timestamp: str = Field(..., description="Server timestamp in ISO format")

# PUBLIC_INTERFACE
class MessageResponse(BaseModel):
    """Standard message response payload."""
    message: str = Field(..., description="Message")


# ========== Auth Models ==========
# PUBLIC_INTERFACE
class RegisterRequest(BaseModel):
    """Request payload to register a new user."""
    email: EmailStr = Field(..., description="User email")
    name: str = Field(..., description="Full name")
    password: str = Field(..., description="Raw password (demo only, in-memory)")

# PUBLIC_INTERFACE
class LoginRequest(BaseModel):
    """Request payload to authenticate a user."""
    email: EmailStr = Field(..., description="User email")
    password: str = Field(..., description="Raw password (demo only, in-memory)")

# PUBLIC_INTERFACE
class AuthUser(BaseModel):
    """User details without password."""
    id: str = Field(..., description="User identifier")
    email: EmailStr = Field(..., description="User email")
    name: str = Field(..., description="Full name")
    created_at: str = Field(..., description="ISO timestamp of creation")

# PUBLIC_INTERFACE
class AuthUserWithRole(AuthUser):
    """User details with role for session context."""
    role: str = Field(..., description="User role (admin|manager|user)")

# PUBLIC_INTERFACE
class AuthResponse(BaseModel):
    """Authentication response with a bearer token and user."""
    token: str = Field(..., description="Session token")
    user: AuthUserWithRole = Field(..., description="Authenticated user profile with role")


# ========== Project Models ==========
# PUBLIC_INTERFACE
class ProjectCreate(BaseModel):
    """Create project request model."""
    name: str = Field(..., description="Project name")
    description: Optional[str] = Field(None, description="Project description")
    owner_id: Optional[str] = Field(None, description="Owner user id")

# PUBLIC_INTERFACE
class ProjectUpdate(BaseModel):
    """Update project request model."""
    name: Optional[str] = Field(None, description="Project name")
    description: Optional[str] = Field(None, description="Project description")

# PUBLIC_INTERFACE
class Project(BaseModel):
    """Project response model."""
    id: str = Field(..., description="Project id")
    name: str = Field(..., description="Project name")
    description: Optional[str] = Field(None, description="Project description")
    owner_id: Optional[str] = Field(None, description="Owner user id")
    created_at: str = Field(..., description="Creation time (ISO)")
    updated_at: str = Field(..., description="Last update time (ISO)")


# ========== Task Models ==========
# PUBLIC_INTERFACE
class TaskCreate(BaseModel):
    """Create task request model."""
    project_id: str = Field(..., description="Related project id")
    title: str = Field(..., description="Task title")
    description: Optional[str] = Field(None, description="Task description")
    assignee_id: Optional[str] = Field(None, description="User id of assignee")
    status: str = Field("open", description="Task status (open, in_progress, done)")

# PUBLIC_INTERFACE
class TaskUpdate(BaseModel):
    """Update task request model."""
    title: Optional[str] = Field(None, description="Task title")
    description: Optional[str] = Field(None, description="Task description")
    assignee_id: Optional[str] = Field(None, description="User id of assignee")
    status: Optional[str] = Field(None, description="Task status")

# PUBLIC_INTERFACE
class Task(BaseModel):
    """Task response model."""
    id: str = Field(..., description="Task id")
    project_id: str = Field(..., description="Related project id")
    title: str = Field(..., description="Task title")
    description: Optional[str] = Field(None, description="Task description")
    assignee_id: Optional[str] = Field(None, description="User id of assignee")
    status: str = Field(..., description="Task status")
    created_at: str = Field(..., description="Creation time (ISO)")
    updated_at: str = Field(..., description="Last update time (ISO)")


# ========== Resource Models ==========
# PUBLIC_INTERFACE
class ResourceCreate(BaseModel):
    """Create resource request model."""
    name: str = Field(..., description="Resource name")
    type: str = Field(..., description="Resource type (person, equipment, budget)")
    capacity: Optional[int] = Field(None, description="Capacity units, semantic depends on type")
    meta: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

# PUBLIC_INTERFACE
class ResourceUpdate(BaseModel):
    """Update resource request model."""
    name: Optional[str] = Field(None, description="Resource name")
    type: Optional[str] = Field(None, description="Resource type")
    capacity: Optional[int] = Field(None, description="Capacity units")
    meta: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

# PUBLIC_INTERFACE
class Resource(BaseModel):
    """Resource response model."""
    id: str = Field(..., description="Resource id")
    name: str = Field(..., description="Resource name")
    type: str = Field(..., description="Resource type")
    capacity: Optional[int] = Field(None, description="Capacity units")
    meta: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    created_at: str = Field(..., description="Creation time (ISO)")
    updated_at: str = Field(..., description="Last update time (ISO)")


# ========== Approval Models ==========
# PUBLIC_INTERFACE
class ApprovalCreate(BaseModel):
    """Create approval request model."""
    subject_type: str = Field(..., description="Entity type (project|task|resource)")
    subject_id: str = Field(..., description="Entity id being approved")
    requested_by: str = Field(..., description="User id requesting approval")
    approver_id: Optional[str] = Field(None, description="User id of approver")

# PUBLIC_INTERFACE
class ApprovalUpdate(BaseModel):
    """Update approval request model."""
    status: Optional[str] = Field(None, description="Approval status (pending|approved|rejected)")
    approver_id: Optional[str] = Field(None, description="User id of approver")

# PUBLIC_INTERFACE
class Approval(BaseModel):
    """Approval response model."""
    id: str = Field(..., description="Approval id")
    subject_type: str = Field(..., description="Entity type (project|task|resource)")
    subject_id: str = Field(..., description="Entity id")
    requested_by: str = Field(..., description="Requester user id")
    approver_id: Optional[str] = Field(None, description="Approver user id")
    status: str = Field(..., description="Approval status")
    created_at: str = Field(..., description="Creation time (ISO)")
    updated_at: str = Field(..., description="Last update time (ISO)")


# ========== Reports Models ==========
# PUBLIC_INTERFACE
class SummaryReport(BaseModel):
    """High level report aggregations."""
    total_projects: int = Field(..., description="Total number of projects")
    total_tasks: int = Field(..., description="Total number of tasks")
    open_tasks: int = Field(..., description="Tasks with status 'open'")
    in_progress_tasks: int = Field(..., description="Tasks with status 'in_progress'")
    done_tasks: int = Field(..., description="Tasks with status 'done'")
    total_resources: int = Field(..., description="Total number of resources")
    pending_approvals: int = Field(..., description="Total pending approvals")

# PUBLIC_INTERFACE
class TrendsPoint(BaseModel):
    """Single time point counts for entities, grouped per day."""
    date: str = Field(..., description="Calendar date (YYYY-MM-DD)")
    tasks: int = Field(..., description="Number of tasks created on this date")
    projects: int = Field(..., description="Number of projects created on this date")
    resources: int = Field(..., description="Number of resources created on this date")
    approvals: int = Field(..., description="Number of approvals created on this date")

# PUBLIC_INTERFACE
class TrendsReport(BaseModel):
    """Daily trend counts for key entities."""
    points: List[TrendsPoint] = Field(..., description="List of day-wise counts")


# App initialization with metadata and CORS
app = FastAPI(
    title="Enterprise Resource Management Platform API",
    description="MVP API with in-memory stores for auth, projects, tasks, resources, approvals and reports.",
    version="0.1.0",
    openapi_tags=[
        {"name": "Health", "description": "Service health and metadata"},
        {"name": "Auth", "description": "User authentication and sessions"},
        {"name": "Projects", "description": "Project CRUD operations"},
        {"name": "Tasks", "description": "Task CRUD operations"},
        {"name": "Resources", "description": "Resource CRUD operations"},
        {"name": "Approvals", "description": "Approval workflows"},
        {"name": "Reports", "description": "Aggregated reports"},
    ],
)

frontend_origin = os.getenv("REACT_APP_FRONTEND_URL", "*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin] if frontend_origin != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== Auth/RBAC Dependencies ==========
# PUBLIC_INTERFACE
def parse_bearer_token(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> Optional[str]:
    """Parse bearer token from Authorization header and return token string or None."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None

# PUBLIC_INTERFACE
def get_current_user(token: Optional[str] = Depends(parse_bearer_token)) -> Optional[Dict[str, Any]]:
    """Return current user from a bearer token, or None if not provided/invalid."""
    if not token:
        return None
    session = sessions_store.get(token)
    if not session:
        return None
    user = users_store.get(session.get("user_id"))
    return user

# PUBLIC_INTERFACE
def require_auth(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> Dict[str, Any]:
    """Require an authenticated user; raise 401 if missing."""
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user

# PUBLIC_INTERFACE
def role_required(allowed_roles: List[str]) -> Callable:
    """Dependency factory to enforce that the current user has one of the allowed roles."""
    def _dependency(user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
        role = user.get("role")
        if role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden: insufficient role")
        return user
    return _dependency


# ========== Health Routes ==========
health_router = APIRouter(prefix="", tags=["Health"])

@health_router.get("/", summary="Health Check", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Health check endpoint to verify the service is running."""
    return HealthResponse(status="ok", timestamp=now_iso())


# ========== Auth Routes ==========
auth_router = APIRouter(prefix="/api/auth", tags=["Auth"])

@auth_router.post("/register", summary="Register", response_model=AuthUser)
def register(req: RegisterRequest) -> AuthUser:
    """Register a new user in the in-memory store."""
    # Simple uniqueness check by email
    for u in users_store.list():
        if u["email"].lower() == req.email.lower():
            raise HTTPException(status_code=400, detail="Email already registered")

    user_data = {
        "id": str(uuid4()),
        "email": str(req.email),
        "name": req.name,
        "password": req.password,  # For MVP only; do NOT store plain passwords in real apps
        "role": "user",
        "created_at": now_iso(),
    }
    users_store.create(user_data)
    return AuthUser(id=user_data["id"], email=user_data["email"], name=user_data["name"], created_at=user_data["created_at"])

@auth_router.post("/login", summary="Login", response_model=AuthResponse)
def login(req: LoginRequest) -> AuthResponse:
    """Login and return a session token."""
    # naive auth
    found = None
    for u in users_store.list():
        if u["email"].lower() == req.email.lower() and u["password"] == req.password:
            found = u
            break
    if not found:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = str(uuid4())
    sessions_store.create({"id": token, "user_id": found["id"], "created_at": now_iso()})
    return AuthResponse(
        token=token,
        user=AuthUserWithRole(id=found["id"], email=found["email"], name=found["name"], created_at=found["created_at"], role=found.get("role","user"))
    )

# PUBLIC_INTERFACE
@auth_router.get("/me", summary="Get current user", response_model=AuthUserWithRole)
def me(user: Dict[str, Any] = Depends(require_auth)) -> AuthUserWithRole:
    """Return the currently authenticated user's profile and role."""
    return AuthUserWithRole(id=user["id"], email=user["email"], name=user["name"], created_at=user["created_at"], role=user.get("role","user"))

@auth_router.post("/logout", summary="Logout", response_model=MessageResponse)
def logout(token: Optional[str] = Depends(parse_bearer_token)) -> MessageResponse:
    """Logout by deleting the session token."""
    if not token:
        raise HTTPException(status_code=400, detail="Token required")
    try:
        sessions_store.delete(token)
    except KeyError:
        # idempotent
        pass
    return MessageResponse(message="Logged out")


# ========== Projects Routes ==========
projects_router = APIRouter(prefix="/api/projects", tags=["Projects"])

@projects_router.get("", summary="List Projects", response_model=List[Project])
def list_projects() -> List[Project]:
    """List all projects."""
    return [Project(**p) for p in projects_store.list()]

@projects_router.post("", summary="Create Project", response_model=Project, dependencies=[Depends(role_required(["admin","manager"]))])
def create_project(req: ProjectCreate, user: Dict[str, Any] = Depends(require_auth)) -> Project:
    """Create a new project. Owner is current user if available."""
    owner_id = req.owner_id or user["id"]
    now = now_iso()
    data = {
        "id": str(uuid4()),
        "name": req.name,
        "description": req.description,
        "owner_id": owner_id,
        "created_at": now,
        "updated_at": now,
    }
    projects_store.create(data)
    return Project(**data)

@projects_router.get("/{project_id}", summary="Get Project", response_model=Project)
def get_project(project_id: str = Path(...)) -> Project:
    """Retrieve a project by id."""
    p = projects_store.get(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return Project(**p)

@projects_router.put("/{project_id}", summary="Update Project", response_model=Project, dependencies=[Depends(role_required(["admin","manager"]))])
def update_project(project_id: str, req: ProjectUpdate) -> Project:
    """Update an existing project."""
    updates: Dict[str, Any] = {k: v for k, v in req.model_dump(exclude_none=True).items()}
    updates["updated_at"] = now_iso()
    try:
        p = projects_store.update(project_id, updates)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    return Project(**p)

@projects_router.delete("/{project_id}", summary="Delete Project", response_model=MessageResponse, dependencies=[Depends(role_required(["admin"]))])
def delete_project(project_id: str) -> MessageResponse:
    """Delete a project by id."""
    try:
        projects_store.delete(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    # Also delete tasks under this project for cleanliness
    for t in list(tasks_store.list()):
        if t["project_id"] == project_id:
            try:
                tasks_store.delete(t["id"])
            except KeyError:
                pass
    return MessageResponse(message="Project deleted")


# ========== Tasks Routes ==========
tasks_router = APIRouter(prefix="/api/tasks", tags=["Tasks"])

@tasks_router.get("", summary="List Tasks", response_model=List[Task])
def list_tasks(project_id: Optional[str] = Query(None, description="Filter by project id"),
               assignee_id: Optional[str] = Query(None, description="Filter by assignee id"),
               status: Optional[str] = Query(None, description="Filter by status")) -> List[Task]:
    """List tasks with optional filters."""
    items = tasks_store.list()
    if project_id:
        items = [t for t in items if t["project_id"] == project_id]
    if assignee_id:
        items = [t for t in items if t.get("assignee_id") == assignee_id]
    if status:
        items = [t for t in items if t.get("status") == status]
    return [Task(**t) for t in items]

@tasks_router.post("", summary="Create Task", response_model=Task, dependencies=[Depends(role_required(["admin","manager"]))])
def create_task(req: TaskCreate) -> Task:
    """Create a new task under a project."""
    if not projects_store.get(req.project_id):
        raise HTTPException(status_code=400, detail="Invalid project_id")
    now = now_iso()
    data = {
        "id": str(uuid4()),
        "project_id": req.project_id,
        "title": req.title,
        "description": req.description,
        "assignee_id": req.assignee_id,
        "status": req.status,
        "created_at": now,
        "updated_at": now,
    }
    tasks_store.create(data)
    return Task(**data)

@tasks_router.get("/{task_id}", summary="Get Task", response_model=Task)
def get_task(task_id: str) -> Task:
    """Retrieve a task by id."""
    t = tasks_store.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    return Task(**t)

@tasks_router.put("/{task_id}", summary="Update Task", response_model=Task, dependencies=[Depends(role_required(["admin","manager"]))])
def update_task(task_id: str, req: TaskUpdate) -> Task:
    """Update an existing task."""
    updates: Dict[str, Any] = {k: v for k, v in req.model_dump(exclude_none=True).items()}
    updates["updated_at"] = now_iso()
    try:
        t = tasks_store.update(task_id, updates)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    return Task(**t)

@tasks_router.delete("/{task_id}", summary="Delete Task", response_model=MessageResponse, dependencies=[Depends(role_required(["admin"]))])
def delete_task(task_id: str) -> MessageResponse:
    """Delete a task by id."""
    try:
        tasks_store.delete(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    return MessageResponse(message="Task deleted")


# ========== Resources Routes ==========
resources_router = APIRouter(prefix="/api/resources", tags=["Resources"])

@resources_router.get("", summary="List Resources", response_model=List[Resource])
def list_resources(resource_type: Optional[str] = Query(None, alias="type", description="Filter by resource type")) -> List[Resource]:
    """List all resources with optional type filter."""
    items = resources_store.list()
    if resource_type:
        items = [r for r in items if r.get("type") == resource_type]
    return [Resource(**r) for r in items]

@resources_router.post("", summary="Create Resource", response_model=Resource, dependencies=[Depends(role_required(["admin","manager"]))])
def create_resource(req: ResourceCreate) -> Resource:
    """Create a new resource."""
    now = now_iso()
    data = {
        "id": str(uuid4()),
        "name": req.name,
        "type": req.type,
        "capacity": req.capacity,
        "meta": req.meta,
        "created_at": now,
        "updated_at": now,
    }
    resources_store.create(data)
    return Resource(**data)

@resources_router.get("/{resource_id}", summary="Get Resource", response_model=Resource)
def get_resource(resource_id: str) -> Resource:
    """Retrieve a resource."""
    r = resources_store.get(resource_id)
    if not r:
        raise HTTPException(status_code=404, detail="Resource not found")
    return Resource(**r)

@resources_router.put("/{resource_id}", summary="Update Resource", response_model=Resource, dependencies=[Depends(role_required(["admin","manager"]))])
def update_resource(resource_id: str, req: ResourceUpdate) -> Resource:
    """Update a resource."""
    updates: Dict[str, Any] = {k: v for k, v in req.model_dump(exclude_none=True).items()}
    updates["updated_at"] = now_iso()
    try:
        r = resources_store.update(resource_id, updates)
    except KeyError:
        raise HTTPException(status_code=404, detail="Resource not found")
    return Resource(**r)

@resources_router.delete("/{resource_id}", summary="Delete Resource", response_model=MessageResponse, dependencies=[Depends(role_required(["admin"]))])
def delete_resource(resource_id: str) -> MessageResponse:
    """Delete a resource."""
    try:
        resources_store.delete(resource_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Resource not found")
    return MessageResponse(message="Resource deleted")


# ========== Approvals Routes ==========
approvals_router = APIRouter(prefix="/api/approvals", tags=["Approvals"])

@approvals_router.get("", summary="List Approvals", response_model=List[Approval])
def list_approvals(status: Optional[str] = Query(None, description="Filter by status")) -> List[Approval]:
    """List approvals with optional status filter."""
    items = approvals_store.list()
    if status:
        items = [a for a in items if a.get("status") == status]
    return [Approval(**a) for a in items]

@approvals_router.post("", summary="Create Approval", response_model=Approval, dependencies=[Depends(role_required(["admin","manager"]))])
def create_approval(req: ApprovalCreate) -> Approval:
    """Create a new approval request."""
    # Optionally verify subject exists
    if req.subject_type == "project" and not projects_store.get(req.subject_id):
        raise HTTPException(status_code=400, detail="Invalid subject_id for project")
    if req.subject_type == "task" and not tasks_store.get(req.subject_id):
        raise HTTPException(status_code=400, detail="Invalid subject_id for task")
    if req.subject_type == "resource" and not resources_store.get(req.subject_id):
        raise HTTPException(status_code=400, detail="Invalid subject_id for resource")
    now = now_iso()
    data = {
        "id": str(uuid4()),
        "subject_type": req.subject_type,
        "subject_id": req.subject_id,
        "requested_by": req.requested_by,
        "approver_id": req.approver_id,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    approvals_store.create(data)
    return Approval(**data)

@approvals_router.get("/{approval_id}", summary="Get Approval", response_model=Approval)
def get_approval(approval_id: str) -> Approval:
    """Retrieve an approval by id."""
    a = approvals_store.get(approval_id)
    if not a:
        raise HTTPException(status_code=404, detail="Approval not found")
    return Approval(**a)

@approvals_router.put("/{approval_id}", summary="Update Approval", response_model=Approval, dependencies=[Depends(role_required(["admin","manager"]))])
def update_approval(approval_id: str, req: ApprovalUpdate) -> Approval:
    """Update an approval (status/approver)."""
    updates: Dict[str, Any] = {k: v for k, v in req.model_dump(exclude_none=True).items()}
    if "status" in updates and updates["status"] not in {"pending", "approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Invalid status")
    updates["updated_at"] = now_iso()
    try:
        a = approvals_store.update(approval_id, updates)
    except KeyError:
        raise HTTPException(status_code=404, detail="Approval not found")
    return Approval(**a)

@approvals_router.delete("/{approval_id}", summary="Delete Approval", response_model=MessageResponse, dependencies=[Depends(role_required(["admin"]))])
def delete_approval(approval_id: str) -> MessageResponse:
    """Delete an approval."""
    try:
        approvals_store.delete(approval_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Approval not found")
    return MessageResponse(message="Approval deleted")


# ========== Reports Routes ==========
reports_router = APIRouter(prefix="/api/reports", tags=["Reports"])

@reports_router.get("/summary", summary="Summary Report", response_model=SummaryReport, dependencies=[Depends(role_required(["admin","manager"]))])
def summary_report() -> SummaryReport:
    """Return aggregate counts of major entities."""
    tasks = tasks_store.list()
    return SummaryReport(
        total_projects=len(projects_store.list()),
        total_tasks=len(tasks),
        open_tasks=len([t for t in tasks if t.get("status") == "open"]),
        in_progress_tasks=len([t for t in tasks if t.get("status") == "in_progress"]),
        done_tasks=len([t for t in tasks if t.get("status") == "done"]),
        total_resources=len(resources_store.list()),
        pending_approvals=len([a for a in approvals_store.list() if a.get("status") == "pending"]),
    )

@reports_router.get(
    "/trends",
    summary="Trends Report",
    response_model=TrendsReport,
    dependencies=[Depends(role_required(["admin","manager"]))],
)
def trends_report(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD) inclusive"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD) inclusive"),
) -> TrendsReport:
    """Return simple daily counts based on created_at in-memory fields for projects, tasks, resources, approvals."""
    # Build per-day counters
    counters: Dict[str, Dict[str, int]] = {}

    def bump(day: Optional[str], key: str) -> None:
        if not day:
            return
        # Filter by optional window
        if date_from and day < date_from:
            return
        if date_to and day > date_to:
            return
        if day not in counters:
            counters[day] = {"tasks": 0, "projects": 0, "resources": 0, "approvals": 0}
        counters[day][key] += 1

    for p in projects_store.list():
        bump(_iso_to_date_str(p.get("created_at")), "projects")
    for t in tasks_store.list():
        bump(_iso_to_date_str(t.get("created_at")), "tasks")
    for r in resources_store.list():
        bump(_iso_to_date_str(r.get("created_at")), "resources")
    for a in approvals_store.list():
        bump(_iso_to_date_str(a.get("created_at")), "approvals")

    points: List[TrendsPoint] = []
    for day in sorted(counters.keys()):
        c = counters[day]
        points.append(TrendsPoint(date=day, tasks=c["tasks"], projects=c["projects"], resources=c["resources"], approvals=c["approvals"]))
    return TrendsReport(points=points)

@reports_router.get(
    "/export",
    summary="Export Tasks CSV",
    description="CSV download for tasks with key fields: id,project_id,title,assignee_id,status,created_at,updated_at",
    dependencies=[Depends(role_required(['admin','manager']))],
    response_class=StreamingResponse,
)
def export_tasks_csv(
    project_id: Optional[str] = Query(None, description="Filter by project id"),
    status: Optional[str] = Query(None, description="Filter by status"),
) -> StreamingResponse:
    """Stream a CSV of tasks from the in-memory store with a simple filter."""
    # Prepare data
    items = tasks_store.list()
    if project_id:
        items = [t for t in items if t.get("project_id") == project_id]
    if status:
        items = [t for t in items if t.get("status") == status]

    headers = ["id", "project_id", "title", "assignee_id", "status", "created_at", "updated_at"]

    def row_iter() -> Iterable[str]:
        # header
        yield ",".join(headers) + "\n"
        for t in items:
            vals = [
                str(t.get("id", "")),
                str(t.get("project_id", "")),
                '"' + str(t.get("title", "")).replace('"', '""') + '"',
                str(t.get("assignee_id", "")) if t.get("assignee_id") is not None else "",
                str(t.get("status", "")),
                str(t.get("created_at", "")),
                str(t.get("updated_at", "")),
            ]
            yield ",".join(vals) + "\n"

    filename = f"tasks_export_{datetime.utcnow().date().isoformat()}.csv"
    return StreamingResponse(row_iter(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# Register routers
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(tasks_router)
app.include_router(resources_router)
app.include_router(approvals_router)
app.include_router(reports_router)
