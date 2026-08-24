"""Project routes."""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.database import get_db
from app.models.schemas import ProjectCreate, ProjectContextAppend, ProjectUpdate
from app.services import context_service, project_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
def list_projects(status: Optional[str] = None, conn: sqlite3.Connection = Depends(get_db)):
    return project_service.list_projects(conn, status=status)


@router.post("", status_code=201)
def create_project(data: ProjectCreate, conn: sqlite3.Connection = Depends(get_db)):
    try:
        return project_service.create_project(conn, data)
    except project_service.ProjectNameConflict as exc:
        raise HTTPException(409, f"project name already exists: {exc}")


@router.get("/{project_id}")
def get_project(project_id: int, conn: sqlite3.Connection = Depends(get_db)):
    try:
        return project_service.get_project(conn, project_id)
    except project_service.ProjectNotFound:
        raise HTTPException(404, f"project {project_id} not found")


@router.patch("/{project_id}")
def update_project(project_id: int, data: ProjectUpdate, conn: sqlite3.Connection = Depends(get_db)):
    try:
        return project_service.update_project(conn, project_id, data)
    except project_service.ProjectNotFound:
        raise HTTPException(404, f"project {project_id} not found")
    except project_service.ProjectNameConflict as exc:
        raise HTTPException(409, f"project name already exists: {exc}")


@router.delete("/{project_id}")
def delete_project(project_id: int, conn: sqlite3.Connection = Depends(get_db)):
    try:
        return project_service.delete_project(conn, project_id)
    except project_service.ProjectNotFound:
        raise HTTPException(404, f"project {project_id} not found")


@router.get("/{project_id}/context")
def get_context(project_id: int, conn: sqlite3.Connection = Depends(get_db)):
    try:
        return context_service.get_project_context(conn, project_id)
    except project_service.ProjectNotFound:
        raise HTTPException(404, f"project {project_id} not found")


@router.post("/{project_id}/context/append", status_code=201)
def append_context(project_id: int, data: ProjectContextAppend, conn: sqlite3.Connection = Depends(get_db)):
    try:
        return context_service.append_project_context(conn, project_id, data)
    except project_service.ProjectNotFound:
        raise HTTPException(404, f"project {project_id} not found")
