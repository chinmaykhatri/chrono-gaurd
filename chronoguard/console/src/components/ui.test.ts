import { describe, it, expect } from 'vitest';
import { tone, toneColor } from './ui';
import { csvCell, safeSourceUrl, asRecord, asRows, display, number } from '../api/client';

describe('UI status tone mapping', () => {
  it('maps good states to tone "good"', () => {
    expect(tone('fresh')).toBe('good');
    expect(tone('serve')).toBe('good');
    expect(tone('confirmed')).toBe('good');
    expect(tone('complete')).toBe('good');
    expect(tone('hit_direct')).toBe('good');
  });

  it('maps warning states to tone "warn"', () => {
    expect(tone('due')).toBe('warn');
    expect(tone('serve_swr')).toBe('warn');
    expect(tone('pending')).toBe('warn');
    expect(tone('queued')).toBe('warn');
  });

  it('maps bad states to tone "bad"', () => {
    expect(tone('stale')).toBe('bad');
    expect(tone('evict_regen')).toBe('bad');
    expect(tone('contradicted')).toBe('bad');
    expect(tone('fail_closed')).toBe('bad');
    expect(tone('failed')).toBe('bad');
  });

  it('maps info states to tone "info"', () => {
    expect(tone('passthrough')).toBe('info');
    expect(tone('revalidate_blocking')).toBe('info');
    expect(tone('evict_lazy')).toBe('info');
  });

  it('defaults unknown states to neutral', () => {
    expect(tone('random_state')).toBe('neutral');
    expect(tone(null)).toBe('neutral');
  });

  it('returns valid CSS variables for toneColor', () => {
    expect(toneColor('fresh')).toContain('var(--color-success)');
    expect(toneColor('stale')).toContain('var(--color-error)');
  });
});

describe('API client utilities', () => {
  it('escapes CSV cells properly and sanitizes CSV injection', () => {
    expect(csvCell('hello')).toBe('"hello"');
    expect(csvCell('hello "world"')).toBe('"hello ""world"""');
    // Injection prevention prefix with '
    expect(csvCell('=SUM(A1:A10)')).toBe('"\'=SUM(A1:A10)"');
    expect(csvCell('+12345')).toBe('"\' +12345"'.replace(' ', ''));
  });

  it('validates safe source URLs', () => {
    expect(safeSourceUrl('https://example.com/api')).toBe('https://example.com/api');
    expect(safeSourceUrl('http://docs.python.org')).toBe('http://docs.python.org/');
    expect(safeSourceUrl('javascript:alert(1)')).toBeUndefined();
    expect(safeSourceUrl('ftp://example.com')).toBeUndefined();
    expect(safeSourceUrl('not a url')).toBeUndefined();
  });

  it('handles record parsing', () => {
    expect(asRecord({ a: 1 })).toEqual({ a: 1 });
    expect(asRecord(null)).toEqual({});
    expect(asRecord([1, 2, 3])).toEqual({});

    expect(asRows([{ a: 1 }, { b: 2 }])).toHaveLength(2);
    expect(asRows(null)).toEqual([]);
  });

  it('formats display strings and numbers', () => {
    expect(display(null)).toBe('Unavailable');
    expect(display(42)).toBe('42');
    expect(number(1234.56, 1)).toBe('1,234.6');
    expect(number(null)).toBe('Unavailable');
  });
});

describe('UI component functions', () => {
  it('exports LifecycleInspector, DiffCard, and ProbeWidget', async () => {
    const ui = await import('./ui');
    expect(ui.LifecycleInspector).toBeDefined();
    expect(ui.DiffCard).toBeDefined();
    expect(ui.ProbeWidget).toBeDefined();
  });
});
