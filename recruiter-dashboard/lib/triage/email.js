// Splits a From-style header ("Jane Doe <jane@co.com>", "jane@co.com",
// "\"Doe, Jane\" <jane@co.com>") into its display name and bare address.
export function parseAddress(value) {
  const text = (value || '').trim()
  const angled = text.match(/^(.*?)\s*<([^<>]+)>\s*$/)
  if (angled) {
    const name = angled[1].trim().replace(/^"(.*)"$/, '$1').trim()
    return { name, address: angled[2].trim() }
  }
  return { name: '', address: text }
}
