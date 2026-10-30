import { registerCardAdapter } from '../features/interactive-cards/registry';
import { taskCardAdapter } from '../features/tasks/taskCardAdapter';

// Composition root: future poll/relay adapters register here without teaching
// the chat loop or the generic card host their domain fields and actions.
registerCardAdapter(taskCardAdapter);

import { boardCardAdapter } from '../features/board/boardCardAdapter';
registerCardAdapter(boardCardAdapter);

import { activityAdapters } from "../features/family-activities/activityAdapters";
activityAdapters.forEach(registerCardAdapter);
