import type { Proposal } from "./SourceProposalReview";

export type File = { file_id: string; name: string; web_url: string };
export type Job = {
  id: string; status: string; discovered: number; indexed: number;
  skipped: number; failures: string[]; proposals: Proposal[];
};
export type SourceProvider = "sharepoint" | "drive" | "s3";
export const validId = /^CAND_(?:[0-8]\d{3}|9000)$/;
