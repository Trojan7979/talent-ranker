from uuid import UUID

from .campaigns import CreateCampaignRequest, EditCampaignRequest
from .selection import SelectionRequest, SelectionResponse


class ScreeningPipeline:
    def __init__(self, repository, max_campaign_size: int = 1000):
        self.repo = repository
        self.max_campaign_size = max_campaign_size

    def preview(self, request: SelectionRequest) -> SelectionResponse:
        run = self.repo.resolve_run(request.job_id, request.ranking_run_id)
        if run is None:
            raise LookupError("ranking run not found for job")
        if run["profile_status"] != "approved":
            raise ValueError("ranking run does not use the current approved profile")
        candidates = self.repo.select_ranked(run["run_id"], request.rule, self.max_campaign_size)
        if len(candidates) > self.max_campaign_size:
            raise ValueError("selection exceeds maximum campaign size")
        return SelectionResponse(
            job_id=request.job_id,
            ranking_run_id=run["run_id"],
            job_profile_version_id=run["job_profile_version_id"],
            rule=request.rule,
            candidates=candidates,
            matching_count=len(candidates),
        )

    def propose(self, request: CreateCampaignRequest) -> dict:
        config = self.repo.get_job_config(request.config_id)
        if config is None:
            raise LookupError("screening configuration not found")
        preview = self.preview(
            SelectionRequest(
                job_id=request.job_id, ranking_run_id=request.ranking_run_id, rule=request.rule
            )
        )
        if not preview.candidates:
            raise ValueError("cannot propose an empty campaign")
        if (
            config["job_id"] != request.job_id
            or config["job_profile_version_id"] != preview.job_profile_version_id
        ):
            raise ValueError("screening configuration does not match ranking run")
        return self.repo.create_campaign(
            request, config, [candidate.candidate_id for candidate in preview.candidates]
        )

    def edit(self, campaign_id: UUID, request: EditCampaignRequest) -> dict:
        if len(request.final_candidate_ids) > self.max_campaign_size:
            raise ValueError("final candidate list exceeds maximum campaign size")
        campaign = self.repo.edit_campaign(campaign_id, request)
        if campaign is None:
            raise RuntimeError("campaign is no longer editable at this revision")
        return campaign
