export function dayKey(date: Date) {
  return date.toISOString().slice(0, 10);
}

const lunarDayNames = [
  '初一', '初二', '初三', '初四', '初五', '初六', '初七', '初八', '初九', '初十',
  '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十',
  '廿一', '廿二', '廿三', '廿四', '廿五', '廿六', '廿七', '廿八', '廿九', '三十',
];

export function lunarDateLabel(day: string) {
  if (!day) return '';
  try {
    const formatter = new Intl.DateTimeFormat('zh-CN-u-ca-chinese', {
      year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC',
    });
    // Older engines may silently fall back to a Gregorian calendar.
    if (formatter.resolvedOptions().calendar !== 'chinese') return '';
    const parts = formatter.formatToParts(new Date(`${day}T12:00:00Z`));
    // Chinese-calendar parts include yearName, absent from the TS Intl registry.
    const year = parts.find((part: { type: string }) => part.type === 'yearName')?.value;
    const month = parts.find((part) => part.type === 'month')?.value;
    const name = lunarDayNames[Number(parts.find((part) => part.type === 'day')?.value) - 1];
    return year && month && name ? `${year}年${month}${name}` : '';
  } catch {
    return '';
  }
}
export function monthDays(month: string) {
  const first = new Date(`${month}-01T12:00:00Z`);
  const start = new Date(first);
  start.setUTCDate(1 - ((first.getUTCDay() + 6) % 7));
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setUTCDate(start.getUTCDate() + index);
    return dayKey(date);
  });
}
export function shiftMonth(month: string, delta: number) {
  const date = new Date(`${month}-01T12:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + delta);
  return dayKey(date).slice(0, 7);
}
