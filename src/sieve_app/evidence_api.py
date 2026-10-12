"""Protected, batch-capable evidence reads for recruiter and pipeline consumers."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from talent_ranker.identifiers import validate_candidate_id

from .source_api import Actor

router = APIRouter(prefix='/api/sources', tags=['resume evidence'])


class ExternalEvidence(BaseModel):
    url: str
    kind: Literal['github', 'web', 'unsupported']
    discovered_via: Literal['text', 'hyperlink']
    source_sha256: str
    status: Literal['pending', 'running', 'completed', 'failed', 'blocked', 'unsupported']
    attempts: int
    error_code: str | None
    fetched_at: datetime | None
    evidence: dict


class EvidenceBatch(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator('candidate_ids')
    @classmethod
    def validate_ids(cls, values):
        return list(dict.fromkeys(validate_candidate_id(value) for value in values))


@router.get('/candidates/{candidate_id}/evidence', response_model=list[ExternalEvidence])
def candidate_evidence(candidate_id: str, actor: Actor, request: Request,
                       response: Response):
    try:
        validate_candidate_id(candidate_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    results = request.app.state.evidence_store.get_for_candidates([candidate_id])
    if candidate_id not in results:
        raise HTTPException(404, 'Candidate not found')
    response.headers['Cache-Control'] = 'no-store'
    return results[candidate_id]


@router.post('/evidence/batch', response_model=dict[str, list[ExternalEvidence]])
def batch_evidence(body: EvidenceBatch, actor: Actor, request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return request.app.state.evidence_store.get_for_candidates(body.candidate_ids)
