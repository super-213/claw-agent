"""HTTP adapter; all business validation and authorization stay in the service."""
from typing import Annotated, Literal, Union
from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from services.task_commands import COMMANDS
from services.task_store import TaskError


class TaskItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=500)
    description: str = ''
    category: str | None = None
    space_type: Literal['personal', 'household']
    actionable: bool = True
    completion_mode: Literal['all', 'any'] = 'all'
    assignee_ids: list[str] | None = None


class TimedItem(TaskItem):
    temporal_type: Literal['timed']
    due_date: str | None = None
    due_at: str | None = None
    starts_on: str | None = None
    recurrence: dict | None = None


class UndatedItem(TaskItem):
    temporal_type: Literal['undated']


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str
    operation_index: int = 0
    invocation: dict
    items: list[Annotated[Union[TimedItem, UndatedItem], Field(discriminator='temporal_type')]]


class TaskMutation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str
    operation_index: int = 0
    expected_version: int
    patch: dict = Field(default_factory=dict)


class CardDefinitionPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(default='', min_length=1, max_length=500)
    description: str = ''
    category: str | None = None
    space_type: Literal['personal', 'household'] = 'personal'
    temporal_type: Literal['timed', 'undated'] = 'undated'
    assignee_ids: list[str] = Field(default_factory=list)
    completion_mode: Literal['all', 'any'] = 'all'
    due_date: str | None = None
    due_at: str | None = None
    starts_on: str | None = None
    recurrence: dict | None = None
    literal_time_text: bool = False


class CardOccurrenceAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['complete', 'reopen', 'cancel', 'skip']
    expected_version: int


class CardSave(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str
    expected_task_version: int
    occurrence_id: str | None = None
    expected_occurrence_version: int | None = None
    definition_patch: CardDefinitionPatch = Field(default_factory=CardDefinitionPatch)
    occurrence_patch: dict = Field(default_factory=dict)
    occurrence_action: CardOccurrenceAction | None = None
    action: Literal['save', 'archive', 'claim', 'pause', 'resume'] = 'save'
    scope: Literal['single', 'occurrence', 'future'] = 'single'
    audience_confirmed: bool = False


class DraftItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=500)
    description: str = ''
    category: str | None = None
    due_date: str | None = None
    due_at: str | None = None
    starts_on: str | None = None
    recurrence: dict | None = None


class DraftCommit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str
    expected_version: int
    items: list[DraftItem] = Field(min_length=1, max_length=100)
    space_type: Literal['personal', 'household']
    temporal_type: Literal['timed', 'undated']
    assignee_ids: list[str] = Field(default_factory=list)
    completion_mode: Literal['all', 'any'] = 'all'
    literal_time_text: bool = False


def task_router(get_service, require_user, require_admin, get_card_context=None):
    router = APIRouter(prefix='/api/home', tags=['family-tasks'])

    @router.get('/members')
    def members(user=Depends(require_user)):
        service = get_service()
        # An unbound admin needs this endpoint to perform initial setup.
        actor = None
        if user.get('role') != 'admin':
            actor = service.members.actor(user)
        else:
            try:
                actor = service.members.actor(user)
            except TaskError:
                pass
        return {'members': service.members.list(), 'current_member_id': actor}

    @router.patch('/members/{member_id}')
    def update_member(member_id: str, patch: dict = Body(...), admin=Depends(require_admin)):
        return get_service().members.update(member_id, patch, admin)

    def filters(view: str = 'mine', space_type: str | None = None, temporal_type: str | None = None,
                actionable: bool | None = None, status: str | None = None, assignee_id: str | None = None,
                due_from: str | None = None, due_to: str | None = None, recurring: bool | None = None,
                query: str | None = None, lifecycle: str | None = None, undated: bool = False,
                current_only: bool = False, cursor: str | None = None, limit: int = Query(50, ge=1, le=200)):
        return locals()

    @router.get('/tasks')
    def tasks(params=Depends(filters), user=Depends(require_user)):
        return get_service().list(user, **params)

    @router.get('/tasks/summary')
    def summary(params=Depends(filters), user=Depends(require_user)):
        return get_service().summary(user, **params)

    @router.post('/tasks', status_code=201)
    def create(payload: TaskCreate, user=Depends(require_user)):
        invocation = payload.invocation
        selected = COMMANDS.get(invocation.get('command'))
        if not selected or selected != (invocation.get('space_type'), invocation.get('temporal_type')):
            raise TaskError('invalid_invocation')
        items = [i.model_dump(exclude_none=True) for i in payload.items]
        return get_service().create(user, items, invocation, request_id=payload.request_id,
                                    operation_index=payload.operation_index)

    @router.get('/tasks/{task_id}')
    def detail(task_id: str, user=Depends(require_user)):
        return get_service().get(user, task_id)

    def card_context(user, session_id, write=False):
        if session_id and get_card_context:
            return get_card_context(user, session_id, write=write)
        return None

    @router.get('/tasks/{task_id}/card')
    def get_card(task_id: str, instance_id: str | None = None, session_id: str | None = None,
                 user=Depends(require_user)):
        return get_service().card_get(user, task_id, instance_id=instance_id, context=card_context(user, session_id))

    @router.patch('/tasks/{task_id}/card')
    def save_card(task_id: str, payload: CardSave, session_id: str | None = None, user=Depends(require_user)):
        data = payload.model_dump()
        data['definition_patch'] = payload.definition_patch.model_dump(exclude_unset=True)
        return get_service().card_change(user, task_id, **data, context=card_context(user, session_id, True))

    @router.get('/task-drafts/{draft_id}')
    def get_draft(draft_id: str, session_id: str, user=Depends(require_user)):
        return get_service().draft_get(user, draft_id, card_context(user, session_id))

    @router.post('/task-drafts/{draft_id}/commit')
    def commit_draft(draft_id: str, payload: DraftCommit, session_id: str, user=Depends(require_user)):
        return get_service().draft_commit(user, draft_id, **payload.model_dump(exclude_none=True),
                                           context=card_context(user, session_id, True))

    @router.patch('/tasks/{task_id}')
    def update(task_id: str, payload: TaskMutation, user=Depends(require_user)):
        return get_service().change(user, task_id, 'update', **payload.model_dump())

    @router.post('/tasks/{task_id}/{action}')
    def change(task_id: str, action: Literal['claim', 'pause', 'resume', 'archive', 'leave'],
               payload: TaskMutation, user=Depends(require_user)):
        return get_service().change(user, task_id, action, **payload.model_dump())

    @router.patch('/tasks/{task_id}/occurrences/{occurrence_id}')
    def update_occurrence(task_id: str, occurrence_id: str, payload: TaskMutation, user=Depends(require_user)):
        return get_service().change(user, task_id, 'update_occurrence', occurrence_id=occurrence_id, **payload.model_dump())

    @router.post('/tasks/{task_id}/occurrences/{occurrence_id}/{action}')
    def change_occurrence(task_id: str, occurrence_id: str, action: Literal['complete', 'reopen', 'skip', 'cancel'],
                          payload: TaskMutation, user=Depends(require_user)):
        return get_service().change(user, task_id, action, occurrence_id=occurrence_id, **payload.model_dump())

    @router.get('/tasks-migration/review')
    def migration_review(_admin=Depends(require_admin)):
        return {'records': get_service().store.snapshot()['migration_review']}

    return router
