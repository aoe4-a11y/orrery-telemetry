// Provider failures happen in normal use. Opaque errors cause false diagnoses;
// saving an entire response could leak credentials or generated output.
export function safeErrorText(value, key = '', length = 240) {
  if (typeof value !== 'string' && typeof value !== 'number') return null;
  let text = String(value);
  if (key) text = text.split(key).join('[REDACTED]');
  return text
    .replace(/\bBearer\s+[^\s"'<>]+/gi, 'Bearer [REDACTED]')
    .replace(/\b(?:sk(?:-ant)?|ds|key|token)-[A-Za-z0-9_-]{8,}/gi, '[REDACTED]')
    .replace(/\b(?:api[_-]?key|authorization|password|secret|(?:access_|refresh_)?token)\b["']?\s*[:=]\s*["']?[^\s"',;<>]+/gi, '[REDACTED]')
    .replace(/[A-Za-z0-9_+\/=\-]{32,}/g, '[REDACTED]')
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/[\x00-\x1f\x7f-\x9f]/g, ' ')
    .slice(0, length);
}

export async function providerError(response, key = '') {
  try {
    const value = await response.json();
    const error = value?.error;
    if (!error || typeof error !== 'object' || Array.isArray(error))
      return {available: false, reason: 'structured_error_missing'};
    return {available: true, type: safeErrorText(error.type, key, 80),
      code: safeErrorText(error.code, key, 80), message_prefix: safeErrorText(error.message, key)};
  } catch {
    return {available: false, reason: 'structured_error_unreadable'};
  }
}
