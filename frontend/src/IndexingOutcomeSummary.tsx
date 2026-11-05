import type { Job } from "./sourceTypes";

export function IndexingOutcomeSummary({ job }: { job: Job }) {
  return <>
    <p>{job.analyzed} analyzed</p>
    <p>{job.matched_existing} matched to existing candidates</p>
    {job.status !== "awaiting_review" && <>
      <p>{job.unchanged} unchanged (embeddings already present)</p>
      <p>{job.embedded} newly embedded</p>
      <p>{job.failures.length} failed</p>
      {job.skipped > 0 && <p>{job.skipped} skipped</p>}
    </>}
  </>;
}
