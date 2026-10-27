import { createElement } from 'react';
import type { CardAdapter, CardView, InteractiveCardRef, RegisteredCardAdapter } from './types';

const adapters = new Map<string, RegisteredCardAdapter>();
export function registerCardAdapter<V extends CardView, A>(adapter: CardAdapter<V, A>) {
  if (adapters.has(adapter.kind)) throw new Error(`卡片类型已注册：${adapter.kind}`);
  adapters.set(adapter.kind, {
    ...adapter,
    submit: (ref, action, context, id) => adapter.submit(ref, action as A, context, id),
    render: (props) => createElement(adapter.Renderer, {
      ...props, view: props.view as V, submit: (action: A) => props.submit(action) as Promise<V>,
    }),
  });
}
export function cardAdapter(ref: InteractiveCardRef) {
  const adapter = adapters.get(ref.kind);
  return adapter?.supportedSchemaVersions.includes(ref.schema_version)
    && adapter.resourceTypes.includes(ref.resource?.type) ? adapter : undefined;
}
export function isCardReference(value: unknown): value is InteractiveCardRef {
  if (!value || typeof value !== 'object') return false;
  const ref = value as Partial<InteractiveCardRef>;
  return ref.type === 'interactive_card' && typeof ref.card_id === 'string' && typeof ref.kind === 'string'
    && typeof ref.schema_version === 'number' && !!ref.resource && typeof ref.resource.id === 'string'
    && typeof ref.resource.type === 'string' && ['draft', 'saved'].includes(ref.mode || '');
}
