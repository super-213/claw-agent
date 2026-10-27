import type { ComponentType, ReactElement } from 'react';

export interface CardResource { type: string; id: string; instance_id?: string }
export interface InteractiveCardRef {
  type: 'interactive_card'; schema_version: number; kind: string; mode: 'saved' | 'draft';
  card_id: string; resource: CardResource; source?: { run_id?: string; tool_call_id?: string };
}
export interface CardContext { surface: 'chat' | 'workbench_board'; sessionId?: string }
export interface CardView {
  resource: CardResource; mode: 'saved' | 'draft'; server_now: string;
  valid_until: string | null; next_transition_at: string | null;
  read_only: boolean; read_only_reason: string | null;
  capabilities: { editable_fields: string[]; actions: string[] };
}
export interface CardRenderProps<V extends CardView, A> {
  view: V; reference: InteractiveCardRef; context: CardContext; editKey: string;
  submit: (action: A) => Promise<V>; busy: boolean; verifying: boolean; uncertain: boolean;
  error: string; retry: () => void; refresh: () => void;
  savedSequence: number;
}
export interface CardAdapter<V extends CardView, A> {
  kind: string; resourceTypes: readonly string[]; supportedSchemaVersions: readonly number[];
  load: (ref: InteractiveCardRef, context: CardContext) => Promise<V>;
  submit: (ref: InteractiveCardRef, action: A, context: CardContext, requestId: string) => Promise<V>;
  Renderer: ComponentType<CardRenderProps<V, A>>;
  invalidate?: (ref: InteractiveCardRef) => void;
}
export interface RegisteredCardAdapter {
  kind: string; resourceTypes: readonly string[]; supportedSchemaVersions: readonly number[];
  load: (ref: InteractiveCardRef, context: CardContext) => Promise<CardView>;
  submit: (ref: InteractiveCardRef, action: unknown, context: CardContext, requestId: string) => Promise<CardView>;
  render: (props: CardRenderProps<CardView, unknown>) => ReactElement;
  invalidate?: (ref: InteractiveCardRef) => void;
}
