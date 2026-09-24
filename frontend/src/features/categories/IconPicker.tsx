import { useEffect, useMemo, useState } from "react";
import type { CSSProperties, KeyboardEvent } from "react";

import {
  CATEGORY_ICON_GROUPS,
  findCategoryIcon,
  searchCategoryIcons,
} from "./iconRegistry";
import type { IconGroup } from "./iconRegistry";

type CategoryIconProps = {
  value: string | null | undefined;
  color?: string;
  size?: number;
};

export function CategoryIcon({ value, color, size = 22 }: CategoryIconProps) {
  const definition = findCategoryIcon(value);
  if (!definition) {
    return value ? <span className="legacy-category-icon">{value}</span> : null;
  }
  const Icon = definition.icon;
  return <Icon aria-hidden="true" color={color} size={size} strokeWidth={1.8} />;
}

type IconPickerProps = {
  value: string;
  color: string;
  onChange: (value: string) => void;
};

export function IconPicker({ value, color, onChange }: IconPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState<IconGroup | undefined>();
  const selected = findCategoryIcon(value);
  const results = useMemo(() => searchCategoryIcons(query, group), [group, query]);

  useEffect(() => {
    if (!open) return;
    function closeOnEscape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  function choose(nextValue: string) {
    onChange(nextValue);
    setOpen(false);
    setQuery("");
  }

  function handleGridKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const direction = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!direction) return;
    const next = document.querySelector<HTMLButtonElement>(
      `[data-icon-index="${index + direction}"]`,
    );
    if (next) {
      event.preventDefault();
      next.focus();
    }
  }

  return (
    <div className="icon-picker">
      <button
        aria-haspopup="dialog"
        aria-label={selected ? `Selected icon: ${selected.label}` : "Choose category icon"}
        className="icon-picker-trigger"
        onClick={() => setOpen(true)}
        type="button"
      >
        <span className="icon-picker-preview" style={{ color }}>
          <CategoryIcon value={value} color={color} />
        </span>
        <span>{selected?.label ?? (value ? "Legacy icon" : "No icon")}</span>
        <span className="icon-picker-caret" aria-hidden="true">⌄</span>
      </button>
      {open && (
        <div className="icon-picker-overlay" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setOpen(false);
        }}>
          <section
            aria-label="Choose category icon"
            aria-modal="true"
            className="icon-picker-dialog card"
            onMouseDown={(event) => event.stopPropagation()}
            role="dialog"
          >
            <header className="icon-picker-heading">
              <div>
                <p className="eyebrow">Category icon</p>
                <h2>Choose an icon</h2>
              </div>
              <button className="text-button" onClick={() => setOpen(false)} type="button">
                Close
              </button>
            </header>
            <input
              autoFocus
              aria-label="Search category icons"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search icons"
              type="search"
              value={query}
            />
            <div aria-label="Icon groups" className="icon-picker-groups" role="group">
              <button
                aria-pressed={!group}
                className={`icon-group-filter ${!group ? "active" : ""}`}
                onClick={() => setGroup(undefined)}
                type="button"
              >
                All
              </button>
              {CATEGORY_ICON_GROUPS.map((option) => (
                <button
                  aria-pressed={group === option}
                  className={`icon-group-filter ${group === option ? "active" : ""}`}
                  key={option}
                  onClick={() => setGroup(option)}
                  type="button"
                >
                  {option}
                </button>
              ))}
            </div>
            <div className="icon-picker-grid" role="listbox" aria-label="Available icons">
              <button
                aria-label="No icon"
                aria-selected={!value}
                className={`icon-choice clear-icon ${!value ? "selected" : ""}`}
                onClick={() => choose("")}
                role="option"
                type="button"
              >
                <span aria-hidden="true">×</span>
                <small>None</small>
              </button>
              {results.map((definition, index) => {
                const Icon = definition.icon;
                return (
                  <button
                    aria-label={definition.label}
                    aria-selected={value === definition.key}
                    className={`icon-choice ${value === definition.key ? "selected" : ""}`}
                    data-icon-index={index}
                    key={definition.key}
                    onClick={() => choose(definition.key)}
                    onKeyDown={(event) => handleGridKeyDown(event, index)}
                    role="option"
                    style={{ "--icon-color": color } as CSSProperties}
                    title={definition.label}
                    type="button"
                  >
                    <Icon aria-hidden="true" size={22} strokeWidth={1.8} />
                    <small>{definition.label}</small>
                  </button>
                );
              })}
            </div>
            {results.length === 0 && <p className="empty-state">No matching icons.</p>}
          </section>
        </div>
      )}
    </div>
  );
}
