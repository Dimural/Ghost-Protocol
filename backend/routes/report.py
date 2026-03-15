"""
Ghost Protocol — Post-Game Report Routes

Fetches persisted reports and exports them as downloadable JSON or PDF files.
If a completed match does not have a persisted report yet, the route lazily
generates one so archived matches remain exportable.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from backend.core.match_state import MATCH_STATE_STORE, MatchState, utc_now
from backend.core.report_exporter import REPORT_EXPORTER
from backend.core.report_generator import REPORT_GENERATOR, REPORT_STORE, MatchReport

router = APIRouter(prefix="/api/report", tags=["report"])


@router.get("/{match_id}", response_model=MatchReport)
async def get_report(match_id: str) -> MatchReport:
    _, report = await _resolve_report(match_id)
    return report


@router.get("/{match_id}/export")
async def export_report(
    match_id: str,
    export_format: Literal["json", "pdf"] = Query("json", alias="format"),
) -> Response:
    match_state, report = await _resolve_report(match_id)
    filename = REPORT_EXPORTER.build_download_filename(match_id, export_format)

    if export_format == "json":
        content = REPORT_EXPORTER.build_json_export(match_state, report)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    content = REPORT_EXPORTER.build_pdf_export(match_state, report)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _resolve_report(match_id: str) -> tuple[MatchState, MatchReport]:
    match_state = MATCH_STATE_STORE.load(match_id)
    if match_state is None:
        raise HTTPException(status_code=404, detail=f"Match '{match_id}' was not found.")

    report = REPORT_STORE.load(match_id)
    if report is None:
        if match_state.status != "complete":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Match '{match_id}' is not complete yet. "
                    "Reports can only be viewed or exported after completion."
                ),
            )
        report = await REPORT_GENERATOR.generate(match_state, force=False)

    if (
        match_state.report_id != report.report_id
        or match_state.report_generated_at != report.generated_at
    ):
        synced_state = match_state.model_copy(
            update={
                "report_id": report.report_id,
                "report_generated_at": report.generated_at,
                "updated_at": utc_now(),
            }
        )
        MATCH_STATE_STORE.save(synced_state)
        match_state = synced_state

    return match_state, report
