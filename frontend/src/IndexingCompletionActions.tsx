import { Link } from "react-router-dom";
import type { Job } from "./sourceTypes";

export function IndexingCompletionActions({ job }: { job: Job }) {
  const complete = job.status === "completed" || job.status === "completed_with_errors";
  if (!complete || job.unchanged + job.embedded === 0) return null;
  return <div className="source-job-actions">
    <Link className="source-primary-action" to="/agents/recruitment?start=chat">
      Continue to ranking
    </Link>
    <p>Paste or describe the job requirements in chat to create ranking criteria.</p>
  </div>;
}
