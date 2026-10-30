export const moreSections: Record<string, string> = {
  account: '账号与设置',
  activity: '物品操作记录',
  skills: '技能',
  admin: '家庭成员管理',
  // 保留旧链接；历史对话的日常入口统一在“对话”。
  sessions: '最近对话',
};

export function validMoreSection(section: string | null, admin: boolean) {
  return section && Object.prototype.hasOwnProperty.call(moreSections, section) && (section !== 'admin' || admin)
    ? section
    : null;
}
