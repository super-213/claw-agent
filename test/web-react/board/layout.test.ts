import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { arrangeBoard, boardLayoutKey, bringToFront, ensurePlacements, moveNote, parseBoardLayout, placementInBoard } from '../../../web-react/src/features/board/boardLayout';
import { BoardCanvas } from '../../../web-react/src/features/board/BoardCanvas';
import { emptyBoardData, type BoardView } from '../../../web-react/src/api/board';

let small = false;
const view = (id: string): BoardView => ({ resource: { type: 'board_post', id }, mode: 'saved', post: {
  ...emptyBoardData(), id, created_by: 'A', title: id, version: 1, state: 'active', created_at: '2026-10-27T04:00:00Z', content_blocks: [{ type: 'text', text: '完整内容' }],
}, server_now: '2026-10-27T04:00:00Z', timezone: 'Asia/Shanghai', valid_until: null, next_transition_at: null,
  current_member_id: 'A', members: [{ member_id: 'A', display_name: '作者', status: 'active' }], read_only: false,
  read_only_reason: null, capabilities: { editable_fields: ['title'], actions: ['save'] } });
beforeEach(() => {
  small = false; localStorage.clear();
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: small, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('accepts only finite coordinates and valid stack levels, without letting malformed storage hide notes', () => {
  expect(parseBoardLayout('broken')).toEqual({});
  expect(parseBoardLayout(JSON.stringify({ valid: { x: -500, y: 90000, z: 3 }, missing: { x: 1 }, wrong: { x: '1', y: 2, z: 3 }, huge: { x: 3, y: 3, z: 9000000 } }))).toEqual({ valid: { x: 24, y: 19656, z: 3 } });
});
it('preserves manually overlapped notes while adding new notes and refreshing the feed', () => {
  const original = { a: { x: 140, y: 80, z: 1 }, b: { x: 150, y: 90, z: 2 } };
  const next = ensurePlacements(original, ['new', 'b', 'a']);
  expect(next.a).toBe(original.a); expect(next.b).toBe(original.b);
  expect(next.new).toBeTruthy();
  expect(ensurePlacements(next, ['a', 'new', 'b'])).toBe(next);
});
it('raises the selected paper without changing its position, and permits exact overlap', () => {
  const arranged = arrangeBoard(['a', 'b']);
  const overlapped = moveNote(arranged, 'b', arranged.a.x, arranged.a.y);
  expect(overlapped.b.x).toBe(overlapped.a.x);
  const selected = bringToFront(overlapped, 'a');
  expect(selected.a.z).toBeGreaterThan(selected.b.z);
  expect(selected.a.x).toBe(overlapped.a.x);
});
it('saves keyboard movement for this account and restores it after remounting', async () => {
  const rows = [view('a'), view('b')];
  const mounted = render(React.createElement(BoardCanvas, { rows, userId: 'alice', onOpen: vi.fn(), onPreview: vi.fn() }));
  const handle = screen.getByRole('button', { name: '移动便笺：a' });
  fireEvent.focus(handle);
  fireEvent.keyDown(handle, { key: 'ArrowRight' });
  fireEvent.keyDown(handle, { key: 'ArrowDown', shiftKey: true });
  const saved = parseBoardLayout(localStorage.getItem(boardLayoutKey('alice')));
  expect(saved.a).toMatchObject({ x: 34, y: 64 });
  expect(saved.a.z).toBeGreaterThan(saved.b.z);
  expect(localStorage.getItem(boardLayoutKey('bob'))).toBeNull();
  mounted.unmount();
  const restored = render(React.createElement(BoardCanvas, { rows, userId: 'alice', onOpen: vi.fn(), onPreview: vi.fn() }));
  await waitFor(() => expect(restored.container.querySelector('[data-note-id="a"]')).toHaveStyle({ transform: 'translate3d(34px, 64px, 0)' }));
});
it('only offers a compact overview on phones without changing saved desktop positions', () => {
  small = true;
  const original = arrangeBoard(['a', 'b']); original.a.x = 180;
  localStorage.setItem(boardLayoutKey('alice'), JSON.stringify(original));
  const opened = vi.fn();
  const rendered = render(React.createElement(BoardCanvas, { rows: [view('a'), view('b')], userId: 'alice', onOpen: opened, onPreview: vi.fn() }));
  expect(rendered.container.querySelectorAll('.board-note-compact')).toHaveLength(2);
  fireEvent.click(screen.getAllByRole('button', { name: '查看', exact: true })[0]);
  expect(opened).toHaveBeenCalledWith('a');
  expect(screen.queryByRole('button', { name: '画布', exact: true })).toBeNull();
  expect(screen.queryByRole('button', { name: '总览', exact: true })).toBeNull();
  expect(screen.queryByRole('region', { name: '可自由摆放的留言板画布' })).toBeNull();
  expect(screen.queryByRole('button', { name: '移动便笺：a' })).toBeNull();
  expect(parseBoardLayout(localStorage.getItem(boardLayoutKey('alice'))).a.x).toBe(180);
});

it('keeps a moved note inside the existing board so dragging cannot stretch the page', () => {
  const initial = arrangeBoard(['a']);
  const moved = moveNote(initial, 'a', 18000, 18000, { width: 960, height: 520 });
  expect(moved.a).toMatchObject({ x: 656, y: 176 });
  expect(moved.a.x + 280).toBeLessThan(960);
  expect(moved.a.y + 320).toBeLessThan(520);
});

it('keeps old off-screen placements visible in a bounded board without rewriting stored coordinates', () => {
  const saved = { x: 1400, y: 1200, z: 4 };
  expect(placementInBoard(saved, { width: 960, height: 400 })).toEqual({ x: 656, y: 56, z: 4 });
  expect(saved).toEqual({ x: 1400, y: 1200, z: 4 });
});
