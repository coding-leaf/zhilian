/**
 * 归档课程反悔期剩余时间格式化纯函数。
 *
 * 归档课程在 `purge_after`（archived_at + 7 天）后会被惰性物理清理，
 * UI 需展示剩余可恢复时间。零 Emoji、无副作用、便于单测。
 */

const MS_PER_MINUTE = 60 * 1000;
const MS_PER_HOUR = 60 * MS_PER_MINUTE;
const MS_PER_DAY = 24 * MS_PER_HOUR;

/**
 * 计算归档课程距离物理清理的剩余时间文案。
 *
 * @param purgeAfter 物理清理时间戳（ISO 字符串）；缺省/非法视为已过期。
 * @param now 当前基准时间，默认当前时刻（便于单测注入）。
 * @returns 形如 `剩余 6 天 23 小时` / `剩余 3 小时` / `剩余 12 分钟` / `已过期`。
 */
export function formatPurgeRemaining(purgeAfter?: string | null, now: Date = new Date()): string {
  if (!purgeAfter) {
    return '已过期';
  }
  const purgeTime = new Date(purgeAfter).getTime();
  const nowTime = now.getTime();
  if (Number.isNaN(purgeTime) || Number.isNaN(nowTime)) {
    return '已过期';
  }
  const diff = purgeTime - nowTime;
  if (diff <= 0) {
    return '已过期';
  }

  const days = Math.floor(diff / MS_PER_DAY);
  const hours = Math.floor((diff % MS_PER_DAY) / MS_PER_HOUR);
  if (days > 0) {
    return `剩余 ${days} 天 ${hours} 小时`;
  }
  if (hours > 0) {
    return `剩余 ${hours} 小时`;
  }
  const minutes = Math.max(1, Math.ceil(diff / MS_PER_MINUTE));
  return `剩余 ${minutes} 分钟`;
}
