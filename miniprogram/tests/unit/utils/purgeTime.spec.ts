import { describe, it, expect } from 'vitest';
import { formatPurgeRemaining } from '@/utils/purgeTime';

describe('formatPurgeRemaining', () => {
  const now = new Date('2026-09-27T00:00:00Z');

  it('returns 已过期 for null, undefined, invalid and past timestamps', () => {
    expect(formatPurgeRemaining(null, now)).toBe('已过期');
    expect(formatPurgeRemaining(undefined, now)).toBe('已过期');
    expect(formatPurgeRemaining('not-a-date', now)).toBe('已过期');
    expect(formatPurgeRemaining('2026-09-26T23:59:59Z', now)).toBe('已过期');
  });

  it('formats remaining days and hours for the 7-day grace window', () => {
    expect(formatPurgeRemaining('2026-10-04T00:00:00Z', now)).toBe('剩余 7 天 0 小时');
    expect(formatPurgeRemaining('2026-10-03T05:00:00Z', now)).toBe('剩余 6 天 5 小时');
  });

  it('formats hours when less than one day remains', () => {
    expect(formatPurgeRemaining('2026-09-27T03:00:00Z', now)).toBe('剩余 3 小时');
  });

  it('formats minutes with a minimum of one when under an hour remains', () => {
    expect(formatPurgeRemaining('2026-09-27T00:30:00Z', now)).toBe('剩余 30 分钟');
    expect(formatPurgeRemaining('2026-09-27T00:00:30Z', now)).toBe('剩余 1 分钟');
  });
});
