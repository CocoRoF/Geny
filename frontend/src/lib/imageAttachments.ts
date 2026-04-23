/**
 * Image attachment helpers — runs in the browser, downscales large
 * images before upload to keep the multimodal LLM happy.
 *
 * Anthropic's recommendation (and OpenAI's "high" detail) is to keep
 * the longest edge ≤ 1568 px; larger images are downscaled server-side
 * anyway, so we save bandwidth and avoid hitting the per-file size cap
 * (10 MiB) by downscaling here.
 */

export const MAX_IMAGE_EDGE = 1568;
export const JPEG_QUALITY = 0.8;

const ALLOWED_INPUT_TYPES = new Set([
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/gif',
  'image/heic',
  'image/heif',
]);

/**
 * Downscale an image File to ``MAX_IMAGE_EDGE`` longest edge, encoded
 * as JPEG at ``JPEG_QUALITY``. Returns the original File when already
 * within bounds or when the type is non-image / unsupported.
 *
 * GIF is passed through untouched to preserve animation; LLM providers
 * accept the first frame so this is fine for chat use.
 */
export async function resizeImageIfNeeded(file: File): Promise<File> {
  if (!file.type.startsWith('image/')) return file;
  if (file.type === 'image/gif') return file; // preserve animation
  if (!ALLOWED_INPUT_TYPES.has(file.type)) return file;

  // Skip resize for tiny images — overhead not worth it.
  if (file.size < 256 * 1024) {
    // <256 KiB rarely needs downscaling.
    const dims = await readDimensions(file).catch(() => null);
    if (!dims || (dims.w <= MAX_IMAGE_EDGE && dims.h <= MAX_IMAGE_EDGE)) {
      return file;
    }
  }

  const bitmap = await createImageBitmap(file).catch(() => null);
  if (!bitmap) return file;

  const { width, height } = bitmap;
  const longest = Math.max(width, height);
  if (longest <= MAX_IMAGE_EDGE) {
    bitmap.close?.();
    return file;
  }

  const scale = MAX_IMAGE_EDGE / longest;
  const targetW = Math.round(width * scale);
  const targetH = Math.round(height * scale);

  const canvas = document.createElement('canvas');
  canvas.width = targetW;
  canvas.height = targetH;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    bitmap.close?.();
    return file;
  }
  ctx.drawImage(bitmap, 0, 0, targetW, targetH);
  bitmap.close?.();

  const blob: Blob | null = await new Promise((resolve) =>
    canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY),
  );
  if (!blob) return file;

  // Rewrite the filename's extension to .jpg so the server picks the
  // right MIME after re-detection.
  const base = file.name.replace(/\.[^.]+$/, '') || 'image';
  return new File([blob], `${base}.jpg`, {
    type: 'image/jpeg',
    lastModified: Date.now(),
  });
}

function readDimensions(file: File): Promise<{ w: number; h: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve({ w: img.naturalWidth, h: img.naturalHeight });
    };
    img.onerror = (e) => {
      URL.revokeObjectURL(url);
      reject(e);
    };
    img.src = url;
  });
}

/** Heuristic: a File is treated as an image when its type starts with "image/". */
export function isImageFile(file: File): boolean {
  return !!file.type && file.type.startsWith('image/');
}
