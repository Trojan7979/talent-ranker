import type { JobProfile } from "./api";
import { CompensationFields } from "./CompensationFields";

type Props = {
  profile: JobProfile;
  approvedBy: string;
  busy: boolean;
  onChange: (profile: JobProfile) => void;
  onApprovedByChange: (value: string) => void;
  onApproveAndRank: () => void;
};

const commaList = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);
const lineList = (value: string) => value.split("\n").map((item) => item.trim()).filter(Boolean);
const optionalNumber = (value: string) => (value ? Number(value) : null);

export function CalibrationPanel({
  profile,
  approvedBy,
  busy,
  onChange,
  onApprovedByChange,
  onApproveAndRank,
}: Props) {
  const priorities = profile.priorities;
  const update = (changes: Partial<JobProfile["priorities"]>) =>
    onChange({ ...profile, priorities: { ...priorities, ...changes } });

  return (
    <section className="calibration-panel">
      <h2>Review hiring priorities</h2>
      <p className="hint">
        {profile.status === "draft" ? "Draft" : "Approved"} v{profile.version} · {" "}
        {profile.calibration_metadata?.method === "llm"
          ? `AI-assisted extraction (${profile.calibration_metadata.model}). Verify every criterion against the JD before approval.`
          : "Rule-based extraction. Verify every criterion against the JD before approval."}
      </p>
      <label>
        Must-have requirements
        <textarea
          rows={4}
          value={priorities.must_have_requirements.join("\n")}
          onChange={(event) => update({ must_have_requirements: lineList(event.target.value) })}
        />
      </label>
      <label>
        Preferred requirements
        <textarea
          rows={3}
          value={priorities.preferred_requirements.join("\n")}
          onChange={(event) => update({ preferred_requirements: lineList(event.target.value) })}
        />
      </label>
      <label>
        Must-have skills
        <input
          value={priorities.must_have_skills.join(", ")}
          onChange={(event) => update({ must_have_skills: commaList(event.target.value) })}
        />
      </label>
      <label>
        Preferred skills
        <input
          value={priorities.preferred_skills.join(", ")}
          onChange={(event) => update({ preferred_skills: commaList(event.target.value) })}
        />
      </label>
      <div className="field-row">
        <label>
          Minimum years
          <input
            type="number"
            min={0}
            value={priorities.minimum_years_experience ?? ""}
            onChange={(event) =>
              update({ minimum_years_experience: optionalNumber(event.target.value) })
            }
          />
        </label>
        <label>
          Seniority
          <input
            value={priorities.seniority ?? ""}
            onChange={(event) => update({ seniority: event.target.value || null })}
          />
        </label>
      </div>
      <label>
        Locations
        <input
          value={priorities.location.locations.join(", ")}
          onChange={(event) =>
            update({ location: { ...priorities.location, locations: commaList(event.target.value) } })
          }
        />
      </label>
      <label>
        Work arrangement
        <select
          value={priorities.location.remote_policy ?? ""}
          onChange={(event) =>
            update({
              location: {
                ...priorities.location,
                remote_policy: (event.target.value || null) as
                  | "onsite"
                  | "hybrid"
                  | "remote"
                  | null,
              },
            })
          }
        >
          <option value="">Not specified</option>
          <option value="onsite">On-site</option>
          <option value="hybrid">Hybrid</option>
          <option value="remote">Remote</option>
        </select>
      </label>
      <div className="field-row">
        <label>
          Maximum notice period (days)
          <input
            type="number"
            min={0}
            value={priorities.availability.max_notice_period_days ?? ""}
            onChange={(event) =>
              update({
                availability: {
                  ...priorities.availability,
                  max_notice_period_days: optionalNumber(event.target.value),
                },
              })
            }
          />
        </label>
        <label>
          Target start date
          <input
            type="date"
            value={priorities.availability.target_start_date ?? ""}
            onChange={(event) =>
              update({
                availability: {
                  ...priorities.availability,
                  target_start_date: event.target.value || null,
                },
              })
            }
          />
        </label>
      </div>
      <CompensationFields
        value={priorities.compensation}
        onChange={(compensation) => update({ compensation })}
      />
      <label>
        Approved by
        <input value={approvedBy} onChange={(event) => onApprovedByChange(event.target.value)} />
      </label>
      <button type="button" onClick={onApproveAndRank} disabled={busy || !approvedBy.trim()}>
        {busy
          ? "Working..."
          : profile.status === "draft"
            ? "Approve criteria and rank"
            : "Run ranking again"}
      </button>
    </section>
  );
}
