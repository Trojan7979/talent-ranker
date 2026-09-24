-- Use only in a disposable database after the upstream and screening schemas.
-- This is a persisted ranking *fixture*, not a call to the ranking model.
INSERT INTO jobs (job_id, job_description)
VALUES ('screening-mock-job', 'Mock Python engineer role for screening API validation.')
ON CONFLICT (job_id) DO NOTHING;

INSERT INTO candidates (candidate_id, source_uri, source_sha256, raw_text)
VALUES
  ('CAND_8991', 'mock://screening/8991', encode(digest('screening-mock-8991','sha256'),'hex'), 'Mock Python project A'),
  ('CAND_8992', 'mock://screening/8992', encode(digest('screening-mock-8992','sha256'),'hex'), 'Mock Python project B'),
  ('CAND_8993', 'mock://screening/8993', encode(digest('screening-mock-8993','sha256'),'hex'), 'Mock Python project C'),
  ('CAND_8994', 'mock://screening/8994', encode(digest('screening-mock-8994','sha256'),'hex'), 'Mock Python project D')
ON CONFLICT (candidate_id) DO NOTHING;

INSERT INTO job_profile_versions
  (profile_version_id, job_id, version, status, job_description,
   priorities, approved_at, approved_by)
VALUES
  ('55555555-5555-5555-5555-555555555555', 'screening-mock-job', 1,
   'approved', 'Mock Python engineer role for screening API validation.',
   '{"must_have_skills":["Python"]}', now(), 'mock-recruiter')
ON CONFLICT (profile_version_id) DO NOTHING;

INSERT INTO ranking_runs
  (run_id, job_id, job_profile_version_id, jd_text, model_versions, scoring_config)
VALUES
  ('66666666-6666-6666-6666-666666666666', 'screening-mock-job',
   '55555555-5555-5555-5555-555555555555',
   'Mock Python engineer role for screening API validation.',
   '{"fixture":"manual"}', '{}')
ON CONFLICT (run_id) DO NOTHING;

INSERT INTO ranking_results
  (run_id, candidate_id, rank, score, score_components,
   evidence, requirement_evidence, reasoning)
VALUES
  ('66666666-6666-6666-6666-666666666666', 'CAND_8991', 1, 0.90,
   '{"fixture":0.90}', '["Mock Python evidence A"]', '[]', 'Mock ranking fixture'),
  ('66666666-6666-6666-6666-666666666666', 'CAND_8992', 2, 0.80,
   '{"fixture":0.80}', '["Mock Python evidence B"]', '[]', 'Mock ranking fixture'),
  ('66666666-6666-6666-6666-666666666666', 'CAND_8993', 3, 0.70,
   '{"fixture":0.70}', '["Mock Python evidence C"]', '[]', 'Mock ranking fixture'),
  ('66666666-6666-6666-6666-666666666666', 'CAND_8994', 4, 0.60,
   '{"fixture":0.60}', '["Mock Python evidence D"]', '[]', 'Mock ranking fixture')
ON CONFLICT (run_id, candidate_id) DO NOTHING;
