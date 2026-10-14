// 头像在上传前统一缩为192px PNG，减小传输、数据库存储与手机解码开销。
export async function avatarPNG(file) {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) throw new Error('请选择 PNG、JPEG 或 WebP 图片');
  if (file.size > 4 * 1024 * 1024) throw new Error('头像原图不能超过 4 MB');
  const bitmap = await createImageBitmap(file);
  const canvas = document.createElement('canvas');
  try {
    if (bitmap.width > 4096 || bitmap.height > 4096) throw new Error('请使用长宽不超过 4096 像素的图片');
    canvas.width = canvas.height = 192;
    const edge = Math.min(bitmap.width, bitmap.height);
    canvas.getContext('2d').drawImage(bitmap, (bitmap.width - edge) / 2, (bitmap.height - edge) / 2,
      edge, edge, 0, 0, 192, 192);
    return canvas.toDataURL('image/png');
  } finally {
    bitmap.close(); canvas.width = canvas.height = 0;
  }
}
