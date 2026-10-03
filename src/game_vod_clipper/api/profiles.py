"""Profiles HTTP routes and request operations."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ..analysis.game_profiles import KINDS
from .context import Workspace, WorkspaceDep, public_project
from .schemas import CaptionBody, ProfileBody, ProfileChoice, plain_text

router = APIRouter()


def profile_listing(ctx: Workspace):
    return {"default_id": ctx.profiles.default_id(), "kinds": KINDS,
            "profiles": ctx.profiles.all()}


@router.get("/api/profiles")
async def list_profiles(ctx: WorkspaceDep):
    return profile_listing(ctx)


@router.post("/api/profiles")
async def create_profile(ctx: WorkspaceDep, body: ProfileBody):
    return ctx.profiles.create(body.title, body.notes)


@router.patch("/api/profiles/{profile_id}")
async def update_profile(ctx: WorkspaceDep, profile_id: str, body: ProfileBody):
    return ctx.profiles.update(profile_id, title=body.title, notes=body.notes)


@router.delete("/api/profiles/{profile_id}")
async def delete_profile(ctx: WorkspaceDep, profile_id: str):
    ctx.profiles.delete(profile_id)
    for project in ctx.store.all("projects"):
        if project.get("profile_id") == profile_id:
            ctx.store.patch("projects", project["id"], profile_id="default")
    return profile_listing(ctx)


@router.put("/api/profiles/default")
async def set_default_profile(ctx: WorkspaceDep, body: ProfileChoice):
    ctx.profiles.set_default(body.profile_id)
    return profile_listing(ctx)


@router.post("/api/profiles/{profile_id}/images")
async def add_profile_image(ctx: WorkspaceDep, profile_id: str, request: Request, kind: str, caption: str = ""):
    if len(caption) > 1000:
        raise HTTPException(422, "說明過長。")
    data = await request.body()
    return await asyncio.to_thread(ctx.profiles.add_image, profile_id, kind, plain_text(caption.strip()), data)


@router.patch("/api/profiles/{profile_id}/images/{image_id}")
async def update_profile_image(ctx: WorkspaceDep, profile_id: str, image_id: str, body: CaptionBody):
    return ctx.profiles.update_image(profile_id, image_id, body.caption)


@router.delete("/api/profiles/{profile_id}/images/{image_id}")
async def remove_profile_image(ctx: WorkspaceDep, profile_id: str, image_id: str):
    return ctx.profiles.remove_image(profile_id, image_id)


@router.get("/api/profiles/{profile_id}/images/{image_id}")
async def profile_image(ctx: WorkspaceDep, profile_id: str, image_id: str):
    return FileResponse(ctx.profiles.image_path(profile_id, image_id), media_type="image/jpeg")


@router.put("/api/projects/{project_id}/profile")
async def choose_project_profile(ctx: WorkspaceDep, project_id: str, body: ProfileChoice):
    ctx.get("projects", project_id)
    if body.profile_id not in {None, "default"}:
        ctx.profiles.get(body.profile_id)
    if body.profile_id != "default":
        # The last game picked also applies to later imports, so a new
        # YouTube import does not silently drop back to no references.
        ctx.profiles.set_default(body.profile_id)
    return public_project(ctx.store.patch("projects", project_id, profile_id=body.profile_id))
