import { boardApi, type BoardAction, type BoardView } from '../../api/board';
import type { CardAdapter } from '../interactive-cards/types';
import { BoardChatCard } from './BoardChatCard';

export const boardCardAdapter: CardAdapter<BoardView, BoardAction> = {
  kind: 'board_post', resourceTypes: ['board_post', 'board_post_draft'], supportedSchemaVersions: [1], Renderer: BoardChatCard,
  load: (reference, context) => boardApi.get(reference.resource.id, reference.resource.type === 'board_post_draft', context),
  submit: (_reference, action, context, requestId) => boardApi.mutate(action, requestId, context),
};
