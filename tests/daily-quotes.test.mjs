import test from 'node:test';
import assert from 'node:assert/strict';
import { dailyQuote } from '../web/quotes.js';

test('quote stays the same across refreshes on the same Shanghai day', () => {
  assert.deepEqual(dailyQuote(new Date('2026-10-14T00:00:00+08:00')),
    dailyQuote(new Date('2026-10-14T23:59:59+08:00')));
});

test('quote changes at UTC+8 midnight, including a month boundary', () => {
  assert.notEqual(dailyQuote(new Date('2026-10-31T15:59:59Z')).text,
    dailyQuote(new Date('2026-10-31T16:00:00Z')).text);
  assert.deepEqual(dailyQuote(new Date('2026-10-31T16:00:00Z')),
    dailyQuote(new Date('2026-11-01T00:00:00+08:00')));
});

test('every quote in a rotation has an author and original source', () => {
  const quotes = Array.from({ length: 8 }, (_, i) => dailyQuote(new Date(Date.UTC(2026, 9, 14 + i))));
  assert.equal(new Set(quotes.map(quote => quote.text)).size, 8);
  for (const quote of quotes) {
    assert.ok(quote.author && quote.source);
    assert.equal(new URL(quote.url).hostname, 'ctext.org');
    assert.equal(new URL(quote.url).protocol, 'https:');
  }
});
