import { FormEvent, useState } from 'react';
import { ApiError } from '../../api/client';
import { skillsApi } from '../../api/skills';
import { Modal } from '../../components/ui/Modal';

export function SkillModal({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const [name, setName] = useState('');
  const [content, setContent] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setSaving(true);
    try {
      await skillsApi.create({ name: name.trim(), content: content.trim() });
      setName('');
      setContent('');
      onClose();
      await onSaved();
    } catch (caught) {
      const apiError = caught as ApiError;
      setError(apiError.data?.message || apiError.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} title="添加技能" onClose={onClose}>
      <form className="skill-form" onSubmit={submit}>
        <label className="field-label">
          技能名
          <input className="skill-input" autoComplete="off" placeholder="calculator_ext" value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="field-label">
          Markdown 内容
          <textarea
            className="skill-textarea"
            spellCheck={false}
            placeholder={'# 技能说明\n描述这个技能的使用规则、输出格式和注意事项。'}
            value={content}
            onChange={(event) => setContent(event.target.value)}
          />
        </label>
        <div className="skill-form-error">{error}</div>
        <div className="modal-actions">
          <button className="modal-secondary" type="button" onClick={onClose}>
            取消
          </button>
          <button className="modal-primary" type="submit" disabled={saving}>
            保存
          </button>
        </div>
      </form>
    </Modal>
  );
}
