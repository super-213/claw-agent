export const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024;
export const MAX_ATTACHMENTS = 10;

export async function preparePhoto(file: File, compress: boolean): Promise<{ file: File; note?: string }> {
  const heic = /\.(heic|heif)$/i.test(file.name) || /image\/hei[cf]/i.test(file.type);
  if (!heic && (!compress || !/^image\/(jpeg|png|webp)$/.test(file.type))) return { file };
  const url = URL.createObjectURL(file);
  try {
    const image = new window.Image();
    image.src = url;
    try { await image.decode(); } catch {
      throw new Error(heic ? '此照片为 HEIC，当前浏览器无法转换。请从照片中导出 JPEG，或将相机格式设为“兼容性最佳”后重试。' : '无法读取这张图片，请关闭压缩后重试。');
    }
    const scale = compress ? Math.min(1, 2048 / Math.max(image.naturalWidth, image.naturalHeight)) : 1;
    // Avoid allocating a huge canvas just to convert an unsupported original format.
    if (image.naturalWidth * image.naturalHeight * scale * scale > 24000000) throw new Error('照片像素过大，请启用图片压缩或选择较小照片。');
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('无法处理图片，请选择 JPEG 照片后重试。');
    context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.86));
    if (!blob) throw new Error('图片转换失败，请选择 JPEG 照片后重试。');
    if (!heic && blob.size >= file.size) return { file };
    return { file: new File([blob], file.name.replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg' }), note: heic ? '已转换为 JPEG 副本' : '已压缩为 JPEG 副本' };
  } finally { URL.revokeObjectURL(url); }
}
