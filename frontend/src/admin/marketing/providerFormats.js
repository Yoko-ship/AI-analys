// The server uses this same provider catalog for its final publishing check.
export function publicationFormats(data, account, rubric) {
  const supported = data.platforms.find(row => row.id === account?.platform)?.formats || [];
  return supported.filter(format => account?.formats.includes(format)
    && (!['digest', 'calendar'].includes(rubric) || format === 'post')
    && (rubric !== 'chart' || format !== 'post'));
}
