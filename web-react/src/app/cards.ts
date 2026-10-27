import { registerCardAdapter } from '../features/interactive-cards/registry';
import { taskCardAdapter } from '../features/tasks/taskCardAdapter';

// Composition root: future poll/relay adapters register here without teaching
// the chat loop or the generic card host their domain fields and actions.
registerCardAdapter(taskCardAdapter);
