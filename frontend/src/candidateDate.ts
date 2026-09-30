const twoDigits = (value: number) => String(value).padStart(2, "0");

export function formatIsoDate(value?: string): string {
  if (!value) return "";
  const [year, month, day] = value.split("-");
  return `${month}-${day}-${year}`;
}

export function parseDisplayDate(value: string): string | undefined {
  const match = /^(\d{2})-(\d{2})-(\d{4})$/.exec(value);
  if (!match) return undefined;
  const [, month, day, year] = match;
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  if (date.getUTCFullYear() !== Number(year) || date.getUTCMonth() + 1 !== Number(month)
    || date.getUTCDate() !== Number(day)) return undefined;
  return `${year}-${month}-${day}`;
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  const day = `${twoDigits(date.getMonth() + 1)}-${twoDigits(date.getDate())}-${date.getFullYear()}`;
  return `${day} ${date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}
