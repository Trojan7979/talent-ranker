"""Cookie-backed identity stub for API unit tests."""

from fastapi import HTTPException


class FakeRecruiterIdentity:
    def __init__(self, actors=None, jobs=None):
        self.actors = actors or {"secret": "recruiter"}
        self.job_grants = jobs or {}

    def actor(self, request):
        actor = self.actors.get(request.cookies.get("sieve_recruiter_session"))
        if actor is None:
            raise HTTPException(401, "Sign in")
        return actor

    def jobs(self, actor, workspace):
        return frozenset(self.job_grants.get((actor, workspace), ()))
