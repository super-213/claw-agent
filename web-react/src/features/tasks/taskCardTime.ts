export function localCardTime(timestamp: string | null | undefined, timezone: string) {
  if (!timestamp) return '';
  const parts = new Intl.DateTimeFormat('sv-SE', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(timestamp));
  const get = (type: string) => parts.find(p => p.type === type)?.value || '';
  return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}:${get('second')}`;
}

export function cardTimestamp(day: string, time: string, timezone: string) {
  if (!day || !time) return null;
  const wanted = `${day}T${time.slice(0, 5)}:00`;
  const wall = Date.parse(wanted + 'Z');
  let stamp = wall;
  for (let i = 0; i < 3; i++) {
    const local = Date.parse(localCardTime(new Date(stamp).toISOString(), timezone) + 'Z');
    stamp += wall - local;
  }
  if (localCardTime(new Date(stamp).toISOString(), timezone) !== wanted) throw new Error('这个时间在当前时区不存在，请重新选择。');
  return new Date(stamp).toISOString();
}
