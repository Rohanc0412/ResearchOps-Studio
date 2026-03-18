# Chat Feature

This folder groups the chat page by job instead of keeping everything inside one page file.

- `components/`: small UI pieces used by the chat page
- `lib/`: pure helpers for parsing, exporting, storage, IDs, and run updates
- `types.ts`: chat/report-specific TypeScript types
- `constants.ts`: model choices and empty-state defaults

`ChatViewPage.tsx` should stay focused on wiring data, hooks, and user actions together.
