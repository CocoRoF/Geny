'use client';

/**
 * Minimal JSON-Schema driven form renderer for the Environment Builder.
 *
 * Scope: cover the subset of JSON Schema that artifact config_schemas
 * actually use in-tree — primitives, enums, arrays of primitives, and
 * flat `type: object` nesting. Anything beyond that falls back to a
 * raw JSON textarea so the user still has an editing surface.
 */

import { useMemo } from 'react';

export interface JsonSchema {
  type?: string | string[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  enum?: unknown[];
  items?: JsonSchema;
  default?: unknown;
  description?: string;
  title?: string;
  minimum?: number;
  maximum?: number;
  format?: string;
  [key: string]: unknown;
}

interface Props {
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}

function primaryType(t: string | string[] | undefined): string {
  if (Array.isArray(t)) return t.find(x => x !== 'null') || t[0] || 'string';
  return t || 'string';
}

function isNullable(t: string | string[] | undefined): boolean {
  return Array.isArray(t) && t.includes('null');
}

function Label({
  name,
  schema,
  required,
}: {
  name: string;
  schema: JsonSchema;
  required: boolean;
}) {
  const title = schema.title || name;
  return (
    <div className="flex items-center gap-1">
      <span className="text-[0.75rem] font-medium text-[var(--text-primary)]">
        {title}
      </span>
      {required && (
        <span className="text-[0.625rem] font-semibold text-[var(--danger-color)]">*</span>
      )}
      <code className="text-[0.625rem] font-mono text-[var(--text-muted)]">{name}</code>
    </div>
  );
}

function Description({ schema }: { schema: JsonSchema }) {
  if (!schema.description) return null;
  return (
    <small className="text-[0.6875rem] text-[var(--text-muted)]">{schema.description}</small>
  );
}

function StringField({
  name,
  schema,
  value,
  onChange,
}: {
  name: string;
  schema: JsonSchema;
  value: unknown;
  onChange: (v: string) => void;
}) {
  const placeholder = schema.default != null ? String(schema.default) : '';
  const multiline = schema.format === 'textarea' || name.endsWith('_prompt') || name.endsWith('Prompt');
  if (multiline) {
    return (
      <textarea
        value={typeof value === 'string' ? value : ''}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        rows={4}
        className="py-1.5 px-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.8125rem] text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] resize-y"
      />
    );
  }
  return (
    <input
      type="text"
      value={typeof value === 'string' ? value : ''}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className="py-1.5 px-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.8125rem] text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)]"
    />
  );
}

function NumberField({
  schema,
  value,
  onChange,
  integer,
}: {
  schema: JsonSchema;
  value: unknown;
  onChange: (v: number | null) => void;
  integer: boolean;
}) {
  const displayValue =
    typeof value === 'number'
      ? value
      : typeof value === 'string' && value !== ''
      ? value
      : '';
  return (
    <input
      type="number"
      step={integer ? 1 : 'any'}
      min={typeof schema.minimum === 'number' ? schema.minimum : undefined}
      max={typeof schema.maximum === 'number' ? schema.maximum : undefined}
      value={displayValue as number | string}
      onChange={e => {
        const raw = e.target.value;
        if (raw === '') {
          onChange(null);
          return;
        }
        const parsed = integer ? parseInt(raw, 10) : parseFloat(raw);
        onChange(Number.isNaN(parsed) ? null : parsed);
      }}
      className="py-1.5 px-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.8125rem] text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)]"
    />
  );
}

function BooleanField({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 cursor-pointer select-none">
      <input
        type="checkbox"
        checked={value === true}
        onChange={e => onChange(e.target.checked)}
        className="w-3.5 h-3.5 cursor-pointer"
      />
      <span className="text-[0.75rem] text-[var(--text-secondary)]">
        {value === true ? 'true' : 'false'}
      </span>
    </label>
  );
}

function EnumField({
  schema,
  value,
  onChange,
}: {
  schema: JsonSchema;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const options = schema.enum ?? [];
  return (
    <select
      value={value === undefined || value === null ? '' : String(value)}
      onChange={e => {
        const raw = e.target.value;
        const matched = options.find(o => String(o) === raw);
        onChange(matched ?? raw);
      }}
      className="py-1.5 px-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.8125rem] text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] cursor-pointer"
    >
      <option value="">— (unset) —</option>
      {options.map(opt => (
        <option key={String(opt)} value={String(opt)}>
          {String(opt)}
        </option>
      ))}
    </select>
  );
}

function ArrayOfPrimitivesField({
  schema,
  value,
  onChange,
}: {
  schema: JsonSchema;
  value: unknown;
  onChange: (v: unknown[]) => void;
}) {
  const itemType = primaryType(schema.items?.type);
  const list: unknown[] = Array.isArray(value) ? value : [];
  const serialized = list
    .map(v => (v == null ? '' : String(v)))
    .join(', ');

  return (
    <input
      type="text"
      value={serialized}
      onChange={e => {
        const tokens = e.target.value
          .split(',')
          .map(t => t.trim())
          .filter(Boolean);
        const coerced = tokens.map(tok => {
          if (itemType === 'number') return Number(tok);
          if (itemType === 'integer') return parseInt(tok, 10);
          if (itemType === 'boolean') return tok === 'true';
          return tok;
        });
        onChange(coerced);
      }}
      placeholder={`${itemType}, ${itemType}, …`}
      className="py-1.5 px-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.8125rem] text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] font-mono"
    />
  );
}

function JsonFallbackField({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const text = useMemo(() => {
    try {
      return JSON.stringify(value ?? null, null, 2);
    } catch {
      return '';
    }
  }, [value]);
  return (
    <textarea
      value={text}
      onChange={e => {
        try {
          const parsed = JSON.parse(e.target.value);
          onChange(parsed);
        } catch {
          // Leave previous value alone on invalid JSON. Caller sees the
          // textarea text — committing on blur / save is handled by the
          // parent's own invalid-JSON banner if the container is using
          // this fallback at the top level.
        }
      }}
      rows={4}
      spellCheck={false}
      className="py-1.5 px-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.75rem] leading-[1.5] text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] font-mono resize-y"
    />
  );
}

function renderField(
  name: string,
  schema: JsonSchema,
  value: unknown,
  onChange: (v: unknown) => void,
) {
  // Enum short-circuits all other types
  if (Array.isArray(schema.enum) && schema.enum.length > 0) {
    return <EnumField schema={schema} value={value} onChange={onChange} />;
  }
  const t = primaryType(schema.type);
  switch (t) {
    case 'string':
      return (
        <StringField
          name={name}
          schema={schema}
          value={value}
          onChange={v => onChange(v === '' && isNullable(schema.type) ? null : v)}
        />
      );
    case 'integer':
      return (
        <NumberField
          schema={schema}
          value={value}
          onChange={v => onChange(v)}
          integer
        />
      );
    case 'number':
      return (
        <NumberField
          schema={schema}
          value={value}
          onChange={v => onChange(v)}
          integer={false}
        />
      );
    case 'boolean':
      return <BooleanField value={value} onChange={onChange} />;
    case 'array': {
      const itemType = primaryType(schema.items?.type);
      const primitiveItemTypes = new Set(['string', 'number', 'integer', 'boolean']);
      if (primitiveItemTypes.has(itemType)) {
        return (
          <ArrayOfPrimitivesField schema={schema} value={value} onChange={onChange} />
        );
      }
      return <JsonFallbackField value={value} onChange={onChange} />;
    }
    case 'object':
    default:
      return <JsonFallbackField value={value} onChange={onChange} />;
  }
}

export default function JsonSchemaForm({ schema, value, onChange }: Props) {
  const properties = schema.properties || {};
  const required = new Set(schema.required || []);
  const keys = Object.keys(properties);

  if (keys.length === 0) {
    // Root schema without properties → fall back to raw editor
    return (
      <JsonFallbackField
        value={value}
        onChange={v =>
          onChange((v && typeof v === 'object' && !Array.isArray(v))
            ? (v as Record<string, unknown>)
            : {})
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {keys.map(name => {
        const fieldSchema = properties[name] as JsonSchema;
        const isRequired = required.has(name);
        const fieldValue = value[name];
        const setFieldValue = (v: unknown) =>
          onChange({ ...value, [name]: v });
        return (
          <div key={name} className="flex flex-col gap-1">
            <Label name={name} schema={fieldSchema} required={isRequired} />
            {renderField(name, fieldSchema, fieldValue, setFieldValue)}
            <Description schema={fieldSchema} />
          </div>
        );
      })}
    </div>
  );
}
