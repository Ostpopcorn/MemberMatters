// The tags and attributes the API keeps when a dashboard card is saved
// (clean_html in memberportal/services/sanitize.py, which stamps rel on every
// link), so the admin preview matches the saved card. cardHtml.spec.ts checks
// the tags match.
export const ALLOWED_TAGS = [
  'a',
  'b',
  'br',
  'div',
  'em',
  'i',
  'li',
  'ol',
  'p',
  'span',
  'strong',
  'ul',
];
export const ALLOWED_ATTR = ['href', 'target', 'rel'];

// Mirrors ICON_NAME in the API: only Material Design Icons are loaded.
export const ICON_NAME = /^mdi-[a-z0-9-]+$/;
