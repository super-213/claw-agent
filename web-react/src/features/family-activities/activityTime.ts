// Interpret datetime-local in the household timezone, never the browser timezone.
export function localActivityTime(value: string | null, zone: string) {
  return value ? new Intl.DateTimeFormat('sv-SE', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value)).replace(' ', 'T') : '';
}
export function activityTimeISO(input: string, zone: string): string | null {
  if (!input) return null;
  let time = Date.parse(input + 'Z');
  for (let i = 0; i < 3; i++) {
    const shown = localActivityTime(new Date(time).toISOString(), zone);
    const delta = Date.parse(input + 'Z') - Date.parse(shown + 'Z');
    if (!delta) return new Date(time).toISOString();
    time += delta;
  }
  throw new Error('该家庭时区中此时间不存在，请选择其他时间。');
}
