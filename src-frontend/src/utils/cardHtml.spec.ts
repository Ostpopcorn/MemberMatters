import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { describe, it, expect } from 'vitest';
import { ALLOWED_TAGS } from './cardHtml';

describe('ALLOWED_TAGS', () => {
  it('matches the tags the API keeps', () => {
    const sanitizer = readFileSync(
      fileURLToPath(
        new URL('../../../memberportal/services/sanitize.py', import.meta.url)
      ),
      'utf8'
    );
    const apiTags = sanitizer
      .match(/^ALLOWED_TAGS = \{([^}]*)\}/m)?.[1]
      .match(/"[^"]+"/g)
      ?.map((tag) => tag.slice(1, -1));

    expect([...ALLOWED_TAGS].sort()).toEqual(apiTags?.sort());
  });
});
