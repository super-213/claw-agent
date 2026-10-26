"""Isolated examples for 010 browser validation. Never uses real family data."""
import sys, tempfile, os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
root=Path(tempfile.mkdtemp(prefix='home010-'))
os.environ['HOME_DATA_DIR']=str(root/'home')
os.environ['HOME_REMINDER_DELIVERY_ENABLED']='false'
from datetime import datetime
from zoneinfo import ZoneInfo
import web_app as w
from services.user_store import UserStore
from services.auth_service import AuthSessionStore
from services.family_member_service import FamilyMemberService
from services.family_task_service import FamilyTaskService
from services.task_store import TaskStore
from services.conversation_store import ConversationStore
from agent_runtime import AgentModelResponse, RunStore, ArtifactStore, MemoryStore, ToolCall
w.user_store=UserStore(root/'users.json')
w.auth_sessions=AuthSessionStore()
w.store=ConversationStore(root/'sessions')
w.run_store=RunStore(root/'runs')
w.artifact_store=ArtifactStore(root/'artifacts')
w.memory_store=MemoryStore(root/'memory')
w.file_access_store=TaskStore(root/'file-access.json')
w.family_members=FamilyMemberService(w.home_service,w.user_store)
clock=lambda: datetime(2026,10,23,12,tzinfo=ZoneInfo('Asia/Shanghai'))
w.home_service._now=clock
w.family_tasks=FamilyTaskService(TaskStore(root/'tasks.json'),w.family_members,clock=clock)
a=w.user_store.create_user(username='home010',password='Home010-test',display_name='示例·小林',role='admin')
b=w.user_store.create_user(username='home010b',password='Home010-test',display_name='示例·另一位很长名字的家庭成员',role='user')
for user,mid in [(a,'A'),(b,'B')]:
 w.family_members.update(mid,{'user_id':user['id'],'display_name':user['display_name']},a)
def inv(temporal='timed',space='personal',mentions=['A']):
 return {'command':('家庭' if space=='household' else '')+('日程' if temporal=='timed' else '备忘'),'space_type':space,'temporal_type':temporal,'actionable':True,'completion_mode':'all','mentions':[{'member_id':m} for m in mentions]}
for i,(title,date) in enumerate([('示例·取快递并核对包裹中的物品','2026-10-22'),('示例·倒垃圾','2026-10-23'),('示例·为下周准备食材','2026-10-23')]):
 w.family_tasks.create(a,[{'title':title,'due_date':date}],inv(),request_id='seed'+str(i))
w.family_tasks.create(a,[{'title':'示例·全家一起打扫客厅、整理书架和阳台上的花草','due_date':'2026-10-23'}],inv(space='household',mentions=['A','B']),request_id='multi')
w.family_tasks.create(a,[{'title':'示例·买一把新的厨房剪刀'}],inv('undated'),request_id='undated')
w.home_service.add_inventory_item('fridge',{'name':'示例·牛奶','quantity':1,'unit':'盒','expires_at':'2026-10-24'},a)
w.home_service.add_inventory_item('medicine',{'name':'示例·家庭药箱的备用药品','quantity':1,'unit':'盒','expires_at':'2026-10-21'},a)
w.home_service.add_inventory_item('pantry',{'name':'示例·大米','quantity':1,'unit':'kg'},a)
# Representative chat for visual and interaction checks, scoped to the test admin.
chat=w.store.create_session('你是家庭助手。',title='周末的家庭安排',owner_user_id=a['id'])
w.store.save_messages(chat['id'],chat['messages']+[
 {'role':'user','content':'帮我看看周末要准备什么，整理成一份简短清单。'},
 {'role':'assistant','content':'','tool_calls':[{'id':'preview-query','type':'function','function':{'name':'family_task_list','arguments':'{"view":"visible","status":"open"}'}}]},
 {'role':'tool','name':'family_task_list','tool_call_id':'preview-query','content':'{"status":"success","items":[{"title":"示例·准备周末食材"}]}'},
 {'role':'assistant','content':'可以先从这 **3 件小事** 开始，让周末安排更从容。\n\n### 周末准备清单\n\n- **采购食材**：出门前看看冰箱，优先用完临期的牛奶。\n- **整理客厅**：全家一起收拾书架和阳台。\n- **安排休息**：给自己留出一段空闲时间。\n\n| 时间 | 建议安排 |\n| --- | --- |\n| 周六上午 | 采购与整理 |\n| 周日下午 | 散步或休息 |\n\n如果你确定了时间，可以直接告诉我，我帮你记成日程。', 'usage':{'total_tokens':184,'prompt_tokens':96,'completion_tokens':88}},
])
class FakeLLM:
 model='home010-validation-stub';context_window=32768
 def __init__(self): self.turn=0
 async def __aenter__(self):return self
 async def __aexit__(self,*_):pass
 async def achat_with_tools(self,messages,schemas):
  self.turn+=1
  return AgentModelResponse(tool_calls=[ToolCall('validation-create','family_timed_memo_create',{'items':[{'title':'示例·聊天新增日程','due_date':'2026-10-23'}]})]) if self.turn==1 else AgentModelResponse(content='示例日程已记录。')
 async def astream_with_tools(self,messages,schemas):yield {'type':'done','response':await self.achat_with_tools(messages,schemas)}
w._new_llm_client=lambda:FakeLLM()
print('Isolated example server ready',flush=True)
import uvicorn
uvicorn.run(w.app,host='127.0.0.1',port=int(os.environ.get("HOME010_API_PORT", "8012")),log_level='warning')
