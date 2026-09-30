import { useState } from "react";
import { formatIsoDate, parseDisplayDate } from "./candidateDate";

export function StartDateField({ value, onChange }: {
  value?: string; onChange: (value?: string) => void;
}) {
  const [display, setDisplay] = useState(() => formatIsoDate(value));
  return <label>Earliest start date (MM-DD-YYYY)
    <input type="text" inputMode="numeric" placeholder="MM-DD-YYYY" maxLength={10}
      autoComplete="off" value={display} onChange={(event) => {
        const next = event.target.value;
        setDisplay(next);
        onChange(parseDisplayDate(next));
      }} />
  </label>;
}
