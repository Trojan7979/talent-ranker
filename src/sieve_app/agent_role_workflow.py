"""Human-approved role setup before an agent uses a saved ranking run."""

import re

from langchain_openai import ChatOpenAI

from talent_ranker.calibration import calibrate_job_description, configured_extractor
from talent_ranker.llm_priority_extraction import CalibrationError
from talent_ranker.priority_extraction import RuleBasedPriorityExtractor
from talent_ranker.schemas import HiringPriorities


def describe_criteria(profile: dict) -> str:
    p = HiringPriorities.model_validate(profile["priorities"])
    lines = [f"Draft hiring criteria for {profile['job_id']} (version {profile['version']}):"]
    for label, values in (
        ("Must-have requirements", p.must_have_requirements),
        ("Must-have skills", p.must_have_skills),
        ("Preferred requirements", p.preferred_requirements),
        ("Preferred skills", p.preferred_skills),
        ("Locations", p.location.locations),
    ):
        lines.append(f"{label}: {', '.join(values) if values else 'Not specified'}")
    lines.extend([
        f"Minimum experience: {p.minimum_years_experience if p.minimum_years_experience is not None else 'Not specified'} years",
        f"Seniority: {p.seniority or 'Not specified'}",
        f"Work arrangement: {p.location.remote_policy or 'Not specified'}",
        f"Maximum notice period: {p.availability.max_notice_period_days if p.availability.max_notice_period_days is not None else 'Not specified'} days",
        f"Target start date: {p.availability.target_start_date or 'Not specified'}",
        f"Compensation: {p.compensation.model_dump(mode='json')}",
        "Review these carefully. To approve and rank, say: 'I approve these criteria; rank top 10 candidates.' You can also say 'Change must-have skills to Python, FastAPI' or ask to see the JD.",
    ])
    return "\n".join(lines)


class AgentRoleWorkflow:
    def __init__(self, settings, ranking_pipeline, store):
        self.settings = settings
        self.pipeline = ranking_pipeline
        self.store = store

    def _draft_jd(self, notes: str, session_id) -> str:
        if len(notes.strip()) < 15:
            raise ValueError("Please include the role, responsibilities, and key requirements so I can draft a JD.")
        model = ChatOpenAI(
            model=self.settings.model,
            api_key=self.settings.api_key,
            base_url=self.settings.base_url,
            timeout=self.settings.model_timeout_seconds,
            max_retries=self.settings.max_retries,
            temperature=0,
        )
        response = model.invoke([
            ("system", "Write a concise job description from the recruiter's notes. Do not invent salary, location, experience, or requirements. Mark missing details as 'To confirm'. Return only the draft JD."),
            ("human", notes),
        ])
        record_usage = getattr(self.store, "record_model_usage", None)
        if callable(record_usage):
            record_usage(
                session_id, "qubrid", self.settings.model, "jd_draft",
                getattr(response, "usage_metadata", None),
            )
        content = response.content
        if not isinstance(content, str) or not 20 <= len(content.strip()) <= 16000:
            raise ValueError("Could not prepare a usable JD draft. Please provide the JD directly.")
        return content.strip()

    def _extract_criteria(self, session: dict, jd: str, expected_stage: str) -> str:
        extractor = None
        metadata = {"method": "rules_fallback"}
        try:
            extractor, metadata = configured_extractor(self.pipeline.settings)
            priorities = calibrate_job_description(jd, extractor=extractor)
        except CalibrationError:
            # A model outage or malformed answer must not force the recruiter to
            # rewrite a valid JD. Keep the fallback grounded in its actual text.
            priorities = RuleBasedPriorityExtractor(metadata).extract(jd)
            metadata["method"] = "rules_fallback"
        finally:
            llm = getattr(extractor, "llm", extractor)
            usage = getattr(llm, "last_usage", None)
            record_usage = getattr(self.store, "record_model_usage", None)
            if usage and callable(record_usage):
                record_usage(session["id"], "qubrid", self.pipeline.settings.calibration_model,
                             "jd_calibration", usage)
        if not (priorities.must_have_skills or priorities.preferred_skills
                or priorities.must_have_requirements or priorities.preferred_requirements):
            return ("I could not identify hiring criteria in this description. "
                    "Please add the role's requirements or responsibilities and try again.")
        if session["job_id"] is None:
            session = self.store.bind_new_job(session["id"])
        profile = self.pipeline.repo.create_job_profile(
            session["job_id"], jd, priorities.model_dump(mode="json"), metadata
        )
        self.store.advance_setup(session["id"], expected_stage, "awaiting_criteria_approval",
                                 draft_job_description=jd,
                                 draft_profile_version_id=profile["profile_version_id"])
        return describe_criteria(profile)

    def handle(self, session: dict, actor: str, message: str) -> str:
        stage = session["setup_stage"]
        value = message.strip()
        lower = value.casefold()
        job = session["job_id"]
        if stage == "awaiting_jd":
            if lower in {"what details do you need to draft a job description?", "what details do you need?"}:
                return "Share the role title, responsibilities, must-have and preferred skills, seniority, location or remote policy, and any salary or notice constraints you know. Missing details can stay 'To confirm'."
            if lower in {"i have a jd to paste", "i have a job description to paste"}:
                return "Paste the full job description in your next message. I will extract hiring criteria for your review."
            if lower.startswith(("write a jd", "write a job description", "draft a jd", "draft a job description")):
                notes = re.sub(r"^(write|draft) a (jd|job description)(?: for| from)?\s*[:,-]?\s*", "", value, flags=re.IGNORECASE)
                if not notes or notes.casefold() in {"me", "this role"}:
                    return "Tell me the role title, responsibilities, must-have skills, and any constraints. I can draft the JD from those notes, or you can paste an existing JD."
                jd = self._draft_jd(notes, session["id"])
            elif len(value) >= 20 and not value.endswith("?") and not lower.startswith(("show ", "find ", "list ", "give me ")):
                return self._extract_criteria(session, value, stage)
            else:
                return "Paste the job description, or say 'Write a JD for ...' with role details. I will show you a draft before anything is approved."
            self.store.advance_setup(session["id"], stage, "awaiting_jd_approval", draft_job_description=jd)
            return (
                f"Here is the JD draft I captured{f' for {job}' if job else ''}:\n\n{jd}\n\n"
                "Is this the full job description you want to use? Reply 'I approve this JD' "
                "to extract hiring criteria for your review. Ranking needs a separate approval. "
                "If these are only notes, say 'Write a JD from these notes' instead."
            )

        if stage == "awaiting_jd_approval":
            if lower in {"show jd", "show the jd", "show job description"}:
                return f"Current JD draft:\n\n{session['draft_job_description']}\n\nReply 'I approve this JD' or paste a replacement."
            if lower in {"i approve this jd", "approve this jd", "approve jd", "i approve the jd"}:
                return self._extract_criteria(session, session["draft_job_description"], stage)
            if lower in {"write a jd from these notes", "draft a jd from these notes"}:
                notes = session["draft_job_description"]
                jd = self._draft_jd(notes, session["id"])
            elif lower.startswith(("write a jd", "write a job description", "draft a jd", "draft a job description")):
                notes = re.sub(r"^(write|draft) a (jd|job description)(?: for| from)?\s*[:,-]?\s*", "", value, flags=re.IGNORECASE)
                if not notes:
                    return "Tell me what to change: role title, responsibilities, skills, and constraints. I will draft a revised JD for approval."
                jd = self._draft_jd(notes, session["id"])
            elif lower.startswith("replace jd:") and len(value[11:].strip()) >= 20:
                jd = value[11:].strip()
            else:
                return "Reply 'I approve this JD', or send 'Replace JD: ...' with the full revised description."
            self.store.advance_setup(session["id"], stage, stage, draft_job_description=jd)
            return f"Revised JD draft:\n\n{jd}\n\nReply 'I approve this JD' to extract hiring criteria."

        if stage == "awaiting_criteria_approval":
            profile = self.pipeline.repo.get_job_profile(str(session["draft_profile_version_id"]))
            if profile is None or profile["job_id"] != job or profile["status"] not in {"draft", "approved"}:
                raise ValueError("The criteria draft is no longer available. Start a new agent session.")
            if lower in {"show criteria", "show hiring criteria", "review criteria"}:
                return describe_criteria(profile)
            if lower in {"show jd", "show the jd", "show job description"}:
                return f"Current JD:\n\n{profile['job_description']}"
            change = re.fullmatch(r"change (must-have skills|preferred skills|must-have requirements|preferred requirements) to (.+)", value, re.IGNORECASE | re.DOTALL)
            if change:
                if profile["status"] != "draft":
                    return "These criteria are already approved. Start a new role session to change them. You can retry the pending ranking here."
                field = change.group(1).casefold().replace("-", "_").replace(" ", "_")
                items = [part.strip() for part in re.split(r",|\n", change.group(2)) if part.strip()]
                if not items or len(items) > 30:
                    return "Provide 1 to 30 comma-separated items for that criterion."
                priorities = dict(profile["priorities"])
                priorities[field] = items
                validated = HiringPriorities.model_validate(priorities)
                updated = self.pipeline.repo.update_job_profile(str(session["draft_profile_version_id"]), validated.model_dump(mode="json"))
                return describe_criteria(updated)
            approval = re.fullmatch(r"(?:i\s+)?approve (?:these |the )?criteria[;,]?\s*rank top (\d{1,4}) candidates?\.?", lower)
            if not approval:
                if profile["status"] == "approved":
                    return "The criteria were approved, but ranking has not completed. Say 'I approve these criteria; rank top 10 candidates' to retry."
                return "I need explicit approval before ranking. Review the criteria, then say 'I approve these criteria; rank top 10 candidates.' To edit a list, say 'Change must-have skills to Python, FastAPI'."
            top_k = int(approval.group(1))
            if not 1 <= top_k <= 1000:
                return "Choose between 1 and 1000 candidates for the shortlist."
            approved = profile if profile["status"] == "approved" else self.pipeline.repo.approve_job_profile(str(session["draft_profile_version_id"]), actor)
            if approved is None:
                raise ValueError("The criteria draft could not be approved. Please review its current status.")
            self.store.queue_ranking(session["id"], approved["profile_version_id"], top_k)
            return f"Criteria approved. Ranking the top {top_k} candidates in the background now. I will post the shortlist here when it is ready; you can leave this page open or return later."

        if stage == "ranking":
            status = self.store.ranking_job(session["id"])
            if status and status["status"] == "failed":
                if lower in {"retry ranking", "try ranking again"} and self.store.retry_ranking(session["id"]):
                    return "Ranking was queued again. I will post the shortlist here when it is ready."
                return "Ranking stopped after repeated failures. Say 'Retry ranking' after the ranking worker is checked. No shortlist was published."
            return "Ranking is running in the background. I will post the saved shortlist here when it finishes."

        raise ValueError("Role setup has already completed")
