import type { HiringPriorities } from "./api";

type Compensation = HiringPriorities["compensation"];

type Props = {
  value: Compensation;
  onChange: (value: Compensation) => void;
};

const optionalNumber = (value: string) => (value ? Number(value) : null);

export function CompensationFields({ value, onChange }: Props) {
  const update = (changes: Partial<Compensation>) => onChange({ ...value, ...changes });

  return (
    <>
      <div className="field-row">
        <label>
          Currency
          <input
            maxLength={3}
            value={value.currency ?? ""}
            onChange={(event) => update({ currency: event.target.value.toUpperCase() || null })}
          />
        </label>
        <label>
          Minimum compensation
          <input
            type="number"
            min={0}
            value={value.minimum ?? ""}
            onChange={(event) => update({ minimum: optionalNumber(event.target.value) })}
          />
        </label>
      </div>
      <div className="field-row">
        <label>
          Maximum compensation
          <input
            type="number"
            min={0}
            value={value.maximum ?? ""}
            onChange={(event) => update({ maximum: optionalNumber(event.target.value) })}
          />
        </label>
        <label>
          Compensation period
          <select
            value={value.period ?? ""}
            onChange={(event) =>
              update({ period: (event.target.value || null) as Compensation["period"] })
            }
          >
            <option value="">Not specified</option>
            <option value="hour">Hourly</option>
            <option value="month">Monthly</option>
            <option value="year">Yearly</option>
          </select>
        </label>
      </div>
    </>
  );
}
