# ADR 0003: Left navigation while preserving the existing UI system

Status: Accepted

## Context

The application already has a coherent build-free HTML/CSS/JavaScript design system and
working Library, Insights, Quick Add, Settings, import, export, localization, history,
and keyboard behaviors. Expansion needs four visible destinations without creating a
second visual language.

## Decision

Use a desktop left rail with the existing PMT monogram and word-labelled Library,
Currently Watching, Rankings, and Insights destinations. Keep Quick Add compact and pin
the existing Settings gear near the bottom. Remove the visible product name and the
theme/import/export controls from persistent chrome; retain document/accessibility
naming and place the existing data actions in Settings. Narrow screens use a simple
wrapped top fallback, not new bottom navigation.

Each view owns URL-restorable state. Currently Watching reuses entry APIs and card
rendering with an active-status query. Rankings uses the existing filter and card
language. Library and Insights calculations remain unchanged.

## Consequences

The structural shell changes but tokens, typography, cards, dialogs, focus styles, and
localization remain authoritative. PWA and bottom navigation remain explicitly deferred.
